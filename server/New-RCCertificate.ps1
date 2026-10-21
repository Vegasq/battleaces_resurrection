$ErrorActionPreference='Stop'
# Generate in memory; no certificate store, external executable or CA setup.
$rsa=[System.Security.Cryptography.RSACryptoServiceProvider]::new(2048)
$cert=$null
try {
    if ($rsa -is [System.Security.Cryptography.RSACryptoServiceProvider]) { $rsa.PersistKeyInCsp=$false }
    $request=[System.Security.Cryptography.X509Certificates.CertificateRequest]::new(
        'CN=Battle Aces Resurrection RC', $rsa,
        [System.Security.Cryptography.HashAlgorithmName]::SHA256,
        [System.Security.Cryptography.RSASignaturePadding]::Pkcs1)
    $cert=$request.CreateSelfSigned([DateTimeOffset]::UtcNow.AddMinutes(-5),[DateTimeOffset]::UtcNow.AddYears(5))
    @{certificate=[Convert]::ToBase64String($cert.RawData);key_xml=$rsa.ToXmlString($true)} | ConvertTo-Json -Compress
} finally {
    if ($cert) { $cert.Dispose() }
    $rsa.Dispose()
}
