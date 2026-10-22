# Infrastructure Health Monitor

A lightweight, configuration-driven Python tool for daily infrastructure health checks. It can monitor Windows and Linux systems, websites, disks, backup freshness, services, SSH connectivity, TCP ports, and Redis health, then deliver a consolidated email report.

The project uses only the Python standard library and is suitable for scheduled execution on Windows or Linux.

## Features

- ICMP reachability checks
- HTTP/HTTPS availability checks
- Local and network disk free-space checks
- Backup-folder freshness checks
- Local or remote Windows service checks
- Linux SSH connectivity and disk checks
- Redis service or custom PING checks over SSH
- SMTP email delivery through SSL or STARTTLS
- Alert-only email mode
- Safe local test mode without sending email
- Configuration validation before checks and email delivery

## Security model

Secrets, private keys, production logs, and the real `config.json` file are intentionally excluded from version control. Never commit credentials, SSH private keys, internal IP addresses, customer data, or production reports.

## Quick start

Requirements:

- Python 3.10 or newer
- `ping` available on the host
- OpenSSH client for Linux checks
- Appropriate permissions for remote Windows service checks

Create a local configuration:

```powershell
Copy-Item .\config.example.json .\config.json
```

Run a test without email delivery:

```powershell
python .\monitor.py --config .\config.json --no-email
```

Configure email variables without storing the application password in a script:

```powershell
.\scripts\set-email-environment.ps1 `
  -SmtpUser "monitor@example.com" `
  -MailFrom "monitor@example.com" `
  -MailTo "admin@example.com"
```

Open a new terminal and run the complete report:

```powershell
python .\monitor.py --config .\config.json
```

For Gmail or Google Workspace, use an application password and port `587` with STARTTLS. Do not use the account's normal password.

## Configuration sections

The following arrays are optional and may be empty:

- `ping_hosts`
- `websites`
- `disk_paths`
- `backup_folders`
- `windows_services`
- `linux_servers`

Start with `config.example.json`, then add only the checks required by your environment.

## Configuration validation

The configuration is validated before any checks run. Invalid section types, missing required fields, incorrect boolean values, and out-of-range numeric settings are reported together. If validation fails, the program exits with a non-zero status without running checks or sending email.

## Testing

Run the automated tests from the repository root:

```powershell
python -m unittest discover -s .\\tests -t . -v
```

## Scheduling

On Windows, run the script with Task Scheduler under a dedicated, least-privileged account. Set the working directory to the repository folder and test the same command manually before enabling the schedule.

## Current status

This is the sanitized initial release of a tool already used for scheduled infrastructure reporting. The public example contains no production configuration or operational data. Planned improvements are tracked in [ROADMAP.md](ROADMAP.md).

