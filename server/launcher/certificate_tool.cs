using System;
using System.Security.Cryptography;
using System.Security.Cryptography.X509Certificates;
using System.Web.Script.Serialization;
// BA_RESURRECTION_NATIVE_CERTIFICATE_V1 -- no trust-store or persistent CSP keys.
internal static class CertificateTool {
    static int Main(string[] args) {
        if (args.Length != 1 || args[0] != "--pipe-certificate" || !Console.IsOutputRedirected) {
            Console.Error.WriteLine("This helper is used privately by Start Server.exe."); return 2;
        }
        try {
            using (var rsa = new RSACryptoServiceProvider(2048)) {
                rsa.PersistKeyInCsp = false;
                var request = new CertificateRequest("CN=Battle Aces Resurrection RC", rsa,
                    HashAlgorithmName.SHA256, RSASignaturePadding.Pkcs1);
                using (var certificate = request.CreateSelfSigned(DateTimeOffset.UtcNow.AddMinutes(-5), DateTimeOffset.UtcNow.AddYears(5))) {
                    Console.Out.Write(new JavaScriptSerializer().Serialize(new {
                        certificate = Convert.ToBase64String(certificate.RawData), key_xml = rsa.ToXmlString(true)
                    }));
                }
            }
            return 0;
        } catch { Console.Error.WriteLine("Windows could not create the server certificate."); return 1; }
    }
}
