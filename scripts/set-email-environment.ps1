[CmdletBinding()]
param(
    [string]$SmtpHost = "smtp.gmail.com",
    [int]$SmtpPort = 587,
    [Parameter(Mandatory = $true)]
    [string]$SmtpUser,
    [Parameter(Mandatory = $true)]
    [string]$MailFrom,
    [Parameter(Mandatory = $true)]
    [string]$MailTo
)

$securePassword = Read-Host "SMTP application password" -AsSecureString
$passwordPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($securePassword)

try {
    $plainPassword = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($passwordPointer)

    [Environment]::SetEnvironmentVariable("SMTP_HOST", $SmtpHost, "User")
    [Environment]::SetEnvironmentVariable("SMTP_PORT", $SmtpPort.ToString(), "User")
    [Environment]::SetEnvironmentVariable("SMTP_USER", $SmtpUser, "User")
    [Environment]::SetEnvironmentVariable("SMTP_PASSWORD", $plainPassword, "User")
    [Environment]::SetEnvironmentVariable("MAIL_FROM", $MailFrom, "User")
    [Environment]::SetEnvironmentVariable("MAIL_TO", $MailTo, "User")

    Write-Host "User-scoped email environment variables were updated."
    Write-Host "Open a new terminal before running the monitor."
}
finally {
    $plainPassword = $null
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($passwordPointer)
}

