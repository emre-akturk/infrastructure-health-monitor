import os
import sys
import ssl
import json
import argparse
import shlex
import shutil
import socket
import smtplib
import logging
import platform
import subprocess
import urllib.request
from pathlib import Path
from datetime import datetime, timedelta
from email.message import EmailMessage


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG_FILE = BASE_DIR / "config.json"
LOG_FILE = BASE_DIR / "health_monitor.log"


logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    encoding="utf-8"
)


def load_config(config_file: Path) -> dict:
    if not config_file.exists():
        raise FileNotFoundError(f"Yapılandırma dosyası bulunamadı: {config_file}")

    with config_file.open("r", encoding="utf-8") as f:
        return json.load(f)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Windows ve Linux sistemleri için altyapı sağlık kontrolü."
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG_FILE,
        help="Yapılandırma dosyasının yolu (varsayılan: config.json)."
    )
    parser.add_argument(
        "--no-email",
        action="store_true",
        help="Raporu ekrana yazdırır ancak e-posta göndermez."
    )
    return parser.parse_args()


def get_env(name: str, default: str | None = None, required: bool = True) -> str:
    value = os.getenv(name, default)
    if required and not value:
        raise RuntimeError(f"Eksik ortam değişkeni: {name}")
    return value


def ping_host(host: str, timeout_ms: int = 1500) -> tuple[bool, str]:
    system = platform.system().lower()

    if system == "windows":
        command = ["ping", "-n", "1", "-w", str(timeout_ms), host]
    else:
        timeout_sec = max(1, int(timeout_ms / 1000))
        command = ["ping", "-c", "1", "-W", str(timeout_sec), host]

    try:
        result = subprocess.run(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True
        )
        return result.returncode == 0, "Ping başarılı" if result.returncode == 0 else "Ping cevabı yok"
    except Exception as exc:
        return False, f"Ping hatası: {exc}"


def check_website(url: str, timeout_sec: int = 10) -> tuple[bool, str]:
    try:
        request = urllib.request.Request(
            url,
            headers={"User-Agent": "IT-Daily-Report/1.0"}
        )

        with urllib.request.urlopen(request, timeout=timeout_sec) as response:
            code = response.getcode()

        if 200 <= code < 400:
            return True, f"HTTP {code}"
        return False, f"HTTP {code}"

    except Exception as exc:
        return False, f"Erişim hatası: {exc}"


def check_disk_path(path: str, warn_free_percent: float = 15) -> tuple[str, str]:
    try:
        usage = shutil.disk_usage(path)

        total_gb = usage.total / (1024 ** 3)
        free_gb = usage.free / (1024 ** 3)
        free_percent = (usage.free / usage.total) * 100 if usage.total else 0

        detail = f"Toplam: {total_gb:.1f} GB | Boş: {free_gb:.1f} GB | Boş oran: %{free_percent:.1f}"

        if free_percent < warn_free_percent:
            return "UYARI", detail

        return "OK", detail

    except Exception as exc:
        return "HATA", f"Disk/klasör okunamadı: {exc}"


def newest_file_mtime(folder: Path, recursive: bool = True) -> datetime | None:
    if not folder.exists():
        return None

    iterator = folder.rglob("*") if recursive else folder.glob("*")
    newest = None

    for item in iterator:
        try:
            if item.is_file():
                mtime = datetime.fromtimestamp(item.stat().st_mtime)
                if newest is None or mtime > newest:
                    newest = mtime
        except OSError:
            continue

    return newest


def check_backup_folder(path: str, warn_older_than_hours: int = 36, recursive: bool = True) -> tuple[str, str]:
    folder = Path(path)

    if not folder.exists():
        return "HATA", f"Klasör bulunamadı: {path}"

    newest = newest_file_mtime(folder, recursive=recursive)

    if newest is None:
        return "HATA", "Klasörde dosya bulunamadı"

    age = datetime.now() - newest
    newest_text = newest.strftime("%d.%m.%Y %H:%M")

    if age > timedelta(hours=warn_older_than_hours):
        return "UYARI", f"Son dosya tarihi eski: {newest_text} | Yaş: {int(age.total_seconds() / 3600)} saat"

    return "OK", f"Son dosya: {newest_text}"


def check_windows_service(computer: str, service: str) -> tuple[str, str]:
    """
    Windows servis kontrolü için sc.exe kullanır.
    Domain yetkin varsa uzak sunucuda da çalışabilir.
    computer boşsa lokal bilgisayarda bakar.
    """

    if platform.system().lower() != "windows":
        return "ATLANDI", "Windows servisi kontrolü sadece Windows üzerinde çalışır"

    target = f"\\\\{computer}" if computer else ""
    command = ["sc.exe"]

    if target:
        command.append(target)

    command.extend(["query", service])

    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=15,
            encoding="utf-8",
            errors="ignore"
        )

        output = (result.stdout or "") + (result.stderr or "")

        if result.returncode != 0:
            return "HATA", output.strip()[:300] or "Servis sorgulanamadı"

        if "RUNNING" in output:
            return "OK", "Çalışıyor"

        if "STOPPED" in output:
            return "UYARI", "Durmuş görünüyor"

        return "UYARI", "Durum net okunamadı"

    except Exception as exc:
        return "HATA", f"Servis kontrol hatası: {exc}"


def check_tcp_port(host: str, port: int, timeout_sec: float = 3) -> tuple[str, str]:
    try:
        with socket.create_connection((host, port), timeout=timeout_sec):
            return "OK", f"TCP {port} portu erişilebilir"
    except TimeoutError:
        return "HATA", f"TCP {port} bağlantısı zaman aşımına uğradı"
    except OSError as exc:
        return "HATA", f"TCP {port} portuna erişilemiyor: {exc}"


def _short_error(stderr: str, stdout: str = "") -> str:
    message = (stderr or stdout or "Bilinmeyen hata").strip()
    return " ".join(message.split())[:300]


def run_ssh_command(
    host: str,
    user: str,
    command_text: str,
    port: int = 22,
    timeout_sec: int = 15,
    identity_file: str = ""
) -> tuple[int, str, str]:
    ssh_executable = shutil.which("ssh")
    if not ssh_executable:
        return -1, "", "Windows OpenSSH istemcisi (ssh.exe) bulunamadı"

    command = [
        ssh_executable,
        "-p", str(port),
        "-o", "BatchMode=yes",
        "-o", f"ConnectTimeout={max(1, timeout_sec)}",
        "-o", "ConnectionAttempts=1",
        "-o", "StrictHostKeyChecking=yes"
    ]

    if identity_file:
        expanded_identity_file = os.path.expandvars(os.path.expanduser(identity_file))
        if not Path(expanded_identity_file).is_file():
            return -1, "", f"SSH anahtar dosyası bulunamadı: {expanded_identity_file}"
        command.extend(["-i", expanded_identity_file])

    command.extend([f"{user}@{host}", command_text])

    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout_sec + 5,
            encoding="utf-8",
            errors="ignore"
        )
        return result.returncode, result.stdout or "", result.stderr or ""
    except subprocess.TimeoutExpired:
        return -1, "", "SSH komutu zaman aşımına uğradı"
    except Exception as exc:
        return -1, "", f"SSH komutu çalıştırılamadı: {exc}"


def check_ssh_login(
    host: str,
    user: str,
    port: int = 22,
    timeout_sec: int = 15,
    identity_file: str = ""
) -> tuple[str, str]:
    returncode, stdout, stderr = run_ssh_command(
        host=host,
        user=user,
        command_text="printf __IT_REPORT_SSH_OK__",
        port=port,
        timeout_sec=timeout_sec,
        identity_file=identity_file
    )

    if returncode == 0 and "__IT_REPORT_SSH_OK__" in stdout:
        return "OK", f"SSH oturumu açıldı ({user}@{host})"

    return "HATA", f"SSH oturumu açılamadı: {_short_error(stderr, stdout)}"


def check_redis_service(
    host: str,
    user: str,
    service: str = "redis-server",
    port: int = 22,
    timeout_sec: int = 15,
    identity_file: str = "",
    check_command: str = "",
    expected_response: str = "+PONG"
) -> tuple[str, str]:
    service_name = shlex.quote(service)
    command_text = check_command or f"systemctl is-active {service_name}"
    returncode, stdout, stderr = run_ssh_command(
        host=host,
        user=user,
        command_text=command_text,
        port=port,
        timeout_sec=timeout_sec,
        identity_file=identity_file
    )
    response = stdout.strip()

    if check_command:
        if returncode == 0 and expected_response.lower() in response.lower():
            return "OK", f"Redis Stack PING yanıtı: {response}"

        if returncode in (-1, 255):
            return "HATA", f"Redis durumu sorgulanamadı: {_short_error(stderr, stdout)}"

        return "UYARI", f"Redis PING yanıtı alınamadı: {_short_error(stderr, stdout)}"

    state = response.lower()

    if returncode == 0 and state == "active":
        return "OK", f"{service} aktif ve çalışıyor"

    if returncode in (-1, 255):
        return "HATA", f"Redis durumu sorgulanamadı: {_short_error(stderr, stdout)}"

    state_text = state or _short_error(stderr, stdout)
    return "UYARI", f"{service} aktif değil | Durum: {state_text}"


def check_linux_disk(
    host: str,
    user: str,
    path: str = "/",
    warn_free_percent: float = 15,
    port: int = 22,
    timeout_sec: int = 15,
    identity_file: str = ""
) -> tuple[str, str]:
    disk_path = shlex.quote(path)
    returncode, stdout, stderr = run_ssh_command(
        host=host,
        user=user,
        command_text=f"df -Pk -- {disk_path}",
        port=port,
        timeout_sec=timeout_sec,
        identity_file=identity_file
    )

    if returncode != 0:
        return "HATA", f"Linux disk bilgisi alınamadı: {_short_error(stderr, stdout)}"

    lines = [item.strip() for item in stdout.splitlines() if item.strip()]
    if len(lines) < 2:
        return "HATA", "Linux disk çıktısı beklenen biçimde değil"

    parts = lines[-1].split()
    if len(parts) < 6:
        return "HATA", "Linux disk çıktısı ayrıştırılamadı"

    try:
        total_kb = int(parts[1])
        used_kb = int(parts[2])
        free_kb = int(parts[3])
    except ValueError:
        return "HATA", "Linux disk değerleri sayısal olarak okunamadı"

    total_gb = total_kb / (1024 ** 2)
    used_gb = used_kb / (1024 ** 2)
    free_gb = free_kb / (1024 ** 2)
    free_percent = (free_kb / total_kb) * 100 if total_kb else 0

    detail = (
        f"{path} | Toplam: {total_gb:.1f} GB | Kullanılan: {used_gb:.1f} GB | "
        f"Boş: {free_gb:.1f} GB | Boş oran: %{free_percent:.1f}"
    )

    if free_percent < warn_free_percent:
        return "UYARI", detail

    return "OK", detail


def line(title: str = "") -> str:
    if title:
        return f"\n--- {title} ---"
    return "-" * 40


def build_report(config: dict) -> tuple[str, bool]:
    now = datetime.now()
    report_lines = []
    has_alert = False

    report_lines.append(f"Günlük IT Sistem Raporu - {now.strftime('%d.%m.%Y %H:%M')}")
    report_lines.append("=" * 52)

    # Ping kontrolleri
    ping_hosts = config.get("ping_hosts", [])
    if ping_hosts:
        report_lines.append(line("Cihaz / Sunucu Ping Kontrolü"))

        for item in ping_hosts:
            name = item.get("name", item.get("host", "Bilinmeyen"))
            host = item.get("host")
            timeout_ms = int(item.get("timeout_ms", 1500))

            if not host:
                continue

            ok, detail = ping_host(host, timeout_ms)
            status = "OK" if ok else "HATA"
            if not ok:
                has_alert = True

            report_lines.append(f"{status:5} | {name} ({host}) | {detail}")

    # Web kontrolleri
    websites = config.get("websites", [])
    if websites:
        report_lines.append(line("Web Sitesi Kontrolü"))

        for item in websites:
            name = item.get("name", item.get("url", "Web"))
            url = item.get("url")

            if not url:
                continue

            ok, detail = check_website(url)
            status = "OK" if ok else "HATA"
            if not ok:
                has_alert = True

            report_lines.append(f"{status:5} | {name} | {url} | {detail}")

    # Disk / klasör boş alan kontrolleri
    disk_paths = config.get("disk_paths", [])
    if disk_paths:
        report_lines.append(line("Disk / Klasör Boş Alan Kontrolü"))

        for item in disk_paths:
            name = item.get("name", item.get("path", "Disk"))
            path = item.get("path")
            warn_free_percent = float(item.get("warn_free_percent", 15))

            if not path:
                continue

            status, detail = check_disk_path(path, warn_free_percent)
            if status in ("UYARI", "HATA"):
                has_alert = True

            report_lines.append(f"{status:5} | {name} | {path} | {detail}")

    # Yedek klasörü kontrolleri
    backup_folders = config.get("backup_folders", [])
    if backup_folders:
        report_lines.append(line("Yedek Klasörü Tarih Kontrolü"))

        for item in backup_folders:
            name = item.get("name", item.get("path", "Yedek"))
            path = item.get("path")
            warn_hours = int(item.get("warn_older_than_hours", 36))
            recursive = bool(item.get("recursive", True))

            if not path:
                continue

            status, detail = check_backup_folder(path, warn_hours, recursive)
            if status in ("UYARI", "HATA"):
                has_alert = True

            report_lines.append(f"{status:5} | {name} | {path} | {detail}")

    # Windows servis kontrolleri
    windows_services = config.get("windows_services", [])
    if windows_services:
        report_lines.append(line("Windows Servis Kontrolü"))

        for item in windows_services:
            name = item.get("name", item.get("service", "Servis"))
            computer = item.get("computer", "")
            service = item.get("service")

            if not service:
                continue

            status, detail = check_windows_service(computer, service)
            if status in ("UYARI", "HATA"):
                has_alert = True

            target = computer if computer else "Lokal"
            report_lines.append(f"{status:7} | {name} | {target} | {service} | {detail}")

    # Linux / Ubuntu sunucu kontrolleri
    linux_servers = config.get("linux_servers", [])
    if linux_servers:
        report_lines.append(line("Linux / Ubuntu Sunucu Kontrolü"))

        for item in linux_servers:
            name = item.get("name", item.get("host", "Linux Sunucu"))
            host = item.get("host")
            user = item.get("user")
            port = int(item.get("port", 22))
            timeout_sec = int(item.get("timeout_sec", 15))
            identity_file = item.get("identity_file", "")
            redis_service = item.get("redis_service", "redis-server")
            redis_check_command = item.get("redis_check_command", "")
            redis_expected_response = item.get("redis_expected_response", "+PONG")
            disk_path = item.get("disk_path", "/")
            warn_free_percent = float(item.get("warn_free_percent", 15))

            if not host or not user:
                has_alert = True
                report_lines.append(f"HATA  | {name} | host veya user bilgisi eksik")
                continue

            port_status, port_detail = check_tcp_port(host, port, min(timeout_sec, 5))
            report_lines.append(f"{port_status:7} | {name} | SSH Portu | {port_detail}")

            if port_status == "HATA":
                has_alert = True
                report_lines.append(f"ATLANDI | {name} | SSH Oturumu | SSH portu erişilemedi")
                report_lines.append(f"ATLANDI | {name} | Redis | SSH portu erişilemedi")
                report_lines.append(f"ATLANDI | {name} | Disk | SSH portu erişilemedi")
                continue

            ssh_status, ssh_detail = check_ssh_login(
                host, user, port, timeout_sec, identity_file
            )
            report_lines.append(f"{ssh_status:7} | {name} | SSH Oturumu | {ssh_detail}")

            if ssh_status == "HATA":
                has_alert = True
                report_lines.append(f"ATLANDI | {name} | Redis | SSH oturumu açılamadı")
                report_lines.append(f"ATLANDI | {name} | Disk | SSH oturumu açılamadı")
                continue

            redis_status, redis_detail = check_redis_service(
                host,
                user,
                redis_service,
                port,
                timeout_sec,
                identity_file,
                redis_check_command,
                redis_expected_response
            )
            if redis_status in ("UYARI", "HATA"):
                has_alert = True
            report_lines.append(f"{redis_status:7} | {name} | Redis | {redis_detail}")

            disk_status, disk_detail = check_linux_disk(
                host,
                user,
                disk_path,
                warn_free_percent,
                port,
                timeout_sec,
                identity_file
            )
            if disk_status in ("UYARI", "HATA"):
                has_alert = True
            report_lines.append(f"{disk_status:7} | {name} | Disk | {disk_detail}")

    report_lines.append(line("Genel Durum"))
    if has_alert:
        report_lines.append("DİKKAT: En az bir kontrolde uyarı veya hata var.")
    else:
        report_lines.append("OK: Kritik sorun görünmüyor.")

    report_lines.append("")
    report_lines.append("Not: Bu rapor Python betiği ile otomatik oluşturulmuştur.")

    return "\n".join(report_lines), has_alert


def send_mail(subject: str, body: str) -> None:
    smtp_host = get_env("SMTP_HOST", "smtp.gmail.com", required=False)
    smtp_port = int(get_env("SMTP_PORT", "587", required=False))
    smtp_user = get_env("SMTP_USER")
    smtp_password = get_env("SMTP_PASSWORD")
    mail_from = get_env("MAIL_FROM", smtp_user, required=False)
    mail_to_raw = get_env("MAIL_TO")

    recipients = [
        email.strip()
        for email in mail_to_raw.replace(";", ",").split(",")
        if email.strip()
    ]

    if not recipients:
        raise RuntimeError("MAIL_TO boş olamaz.")

    message = EmailMessage()
    message["From"] = mail_from
    message["To"] = ", ".join(recipients)
    message["Subject"] = subject
    message.set_content(body)

    context = ssl.create_default_context()

    if smtp_port == 465:
        with smtplib.SMTP_SSL(smtp_host, smtp_port, context=context, timeout=30) as smtp:
            smtp.login(smtp_user, smtp_password)
            smtp.send_message(message)
    else:
        with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as smtp:
            smtp.ehlo()
            smtp.starttls(context=context)
            smtp.ehlo()
            smtp.login(smtp_user, smtp_password)
            smtp.send_message(message)


def main() -> None:
    args = parse_args()
    config = load_config(args.config)
    report, has_alert = build_report(config)

    now = datetime.now()
    subject_prefix = config.get("mail_subject_prefix", "Günlük IT Sistem Raporu")
    send_only_on_alert = bool(config.get("send_only_on_alert", False))

    subject = f"{subject_prefix} - {now.strftime('%d.%m.%Y')}"
    if has_alert:
        subject = "DİKKAT - " + subject

    print(report)

    if args.no_email:
        logging.info("E-posta gönderimi --no-email seçeneğiyle atlandı. Alert=%s", has_alert)
        return

    if send_only_on_alert and not has_alert:
        logging.info("Uyarı yok, mail gönderilmedi. send_only_on_alert=true")
        return

    send_mail(subject, report)
    logging.info("Rapor maili gönderildi. Alert=%s", has_alert)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        logging.exception("Betiğin çalışması sırasında hata oluştu.")
        print(f"HATA: {exc}", file=sys.stderr)
        sys.exit(1)
