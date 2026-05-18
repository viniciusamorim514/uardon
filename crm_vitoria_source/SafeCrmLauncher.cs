using System;
using System.Diagnostics;
using System.IO;
using System.Net.Sockets;
using System.Threading;
using System.Windows.Forms;

internal static class SafeCrmLauncher
{
    private const string Url = "http://127.0.0.1:5000";
    private const int Port = 5000;

    [STAThread]
    private static void Main()
    {
        string sourceDir = @"V:\ARQUIVOS\OneDrive\Documentos\New project\crm_vitoria_source";
        string installedDir = @"V:\ARQUIVOS\OneDrive\" + "\u00C1rea de Trabalho" + @"\CRM Vitoria Uardon";
        string runner = Path.Combine(sourceDir, "run_source_with_installed_data.py");
        string pythonw = Path.Combine(sourceDir, ".venv", "Scripts", "pythonw.exe");
        string python = Path.Combine(sourceDir, ".venv", "Scripts", "python.exe");

        try
        {
            if (!IsPortOpen())
            {
                string pythonExe = File.Exists(pythonw) ? pythonw : python;
                if (!File.Exists(pythonExe) || !File.Exists(runner))
                {
                    MessageBox.Show(
                        "Nao encontrei os arquivos necessarios para abrir o CRM em modo seguro.",
                        "CRM Vitoria Uardon",
                        MessageBoxButtons.OK,
                        MessageBoxIcon.Error
                    );
                    return;
                }

                var startInfo = new ProcessStartInfo
                {
                    FileName = pythonExe,
                    Arguments = Quote(runner),
                    WorkingDirectory = sourceDir,
                    UseShellExecute = false,
                    CreateNoWindow = true,
                    WindowStyle = ProcessWindowStyle.Hidden
                };
                startInfo.EnvironmentVariables["CRM_DATA_FILE"] = Path.Combine(installedDir, "data.json");
                startInfo.EnvironmentVariables["CRM_UPLOAD_DIR"] = Path.Combine(installedDir, "uploads");
                Process.Start(startInfo);

                for (int i = 0; i < 30 && !IsPortOpen(); i++)
                {
                    Thread.Sleep(1000);
                }
            }

            if (!IsPortOpen())
            {
                MessageBox.Show(
                    "O CRM foi iniciado, mas a porta local 5000 nao respondeu. Tente abrir novamente em alguns segundos.",
                    "CRM Vitoria Uardon",
                    MessageBoxButtons.OK,
                    MessageBoxIcon.Warning
                );
                return;
            }

            OpenBrowser();
        }
        catch (Exception ex)
        {
            MessageBox.Show(
                "Nao foi possivel abrir o CRM.\n\n" + ex.Message,
                "CRM Vitoria Uardon",
                MessageBoxButtons.OK,
                MessageBoxIcon.Error
            );
        }
    }

    private static bool IsPortOpen()
    {
        try
        {
            using (var client = new TcpClient())
            {
                var result = client.BeginConnect("127.0.0.1", Port, null, null);
                bool success = result.AsyncWaitHandle.WaitOne(TimeSpan.FromMilliseconds(350));
                if (!success)
                {
                    return false;
                }
                client.EndConnect(result);
                return true;
            }
        }
        catch
        {
            return false;
        }
    }

    private static void OpenBrowser()
    {
        string[] chromePaths =
        {
            @"C:\Program Files\Google\Chrome\Application\chrome.exe",
            @"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"
        };

        foreach (string chromePath in chromePaths)
        {
            if (File.Exists(chromePath))
            {
                Process.Start(new ProcessStartInfo
                {
                    FileName = chromePath,
                    Arguments = Url,
                    UseShellExecute = false
                });
                return;
            }
        }

        Process.Start(new ProcessStartInfo
        {
            FileName = Url,
            UseShellExecute = true
        });
    }

    private static string Quote(string value)
    {
        return "\"" + value.Replace("\"", "\\\"") + "\"";
    }
}
