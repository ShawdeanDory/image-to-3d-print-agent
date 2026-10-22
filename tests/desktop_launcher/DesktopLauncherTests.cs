// 固定CPU/HTTP/进程fixture；不连接云端，不调用模型。
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Net;
using System.Net.Sockets;
using System.Reflection;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using System.Web.Script.Serialization;
using System.Windows.Forms;

public static class DesktopLauncherTests {
    public static int Main(string[] args) {
        if(args.Length==2 && args[0]=="echo") {Console.OutputEncoding=Encoding.UTF8;Console.Write(args[1]);return 0;}
        if(args.Length==1 && args[0]=="sleep") {Thread.Sleep(30000);return 0;}
        var checks=new List<string>();
        try {
            new LauncherConfig().Validate();checks.Add("normal_config");
            foreach(var bad in new[]{new LauncherConfig{ssh_alias="host;calc"},new LauncherConfig{deployment="../other"},new LauncherConfig{ssh_config="../key"},new LauncherConfig{ui_port=9000}}) {
                bool rejected=false;try{bad.Validate();}catch{rejected=true;}if(!rejected)throw new Exception("非法配置未拒绝");checks.Add("invalid_config");
            }
            foreach(string value in new[]{@"C:\目录 with space\", "a\"b", " plain ", "x\\\"y", ""}) {
                var info=new ProcessStartInfo(Application.ExecutablePath,"echo "+Connector.Quote(value)){UseShellExecute=false,CreateNoWindow=true,RedirectStandardOutput=true,StandardOutputEncoding=Encoding.UTF8};
                using(var process=Process.Start(info)) { string actual=process.StandardOutput.ReadToEnd();process.WaitForExit();if(actual!=value)throw new Exception("Windows参数往返失败"); }
                checks.Add("quoted_argument_roundtrip");
            }
            foreach(string body in new[]{"{\"schema_version\":\"runtime-v1\",\"configured_backends\":[\"triposr\"]}","{\"ok\":true}"}) {
                var listener=new TcpListener(IPAddress.Loopback,0);listener.Start();int port=((IPEndPoint)listener.LocalEndpoint).Port;
                var server=Task.Run(()=>{using(var client=listener.AcceptTcpClient())using(var stream=client.GetStream()) {
                    stream.ReadTimeout=3000;var input=new byte[4096];stream.Read(input,0,input.Length);byte[] data=Encoding.UTF8.GetBytes(body);
                    byte[] header=Encoding.ASCII.GetBytes("HTTP/1.1 200 OK\r\nContent-Length: "+data.Length+"\r\nContent-Type: application/json\r\nConnection: close\r\n\r\n");stream.Write(header,0,header.Length);stream.Write(data,0,data.Length);
                }});
                bool actual=Connector.Healthy("http://127.0.0.1:"+port+"/api/v1/configuration");server.Wait(4000);listener.Stop();
                if(actual!=body.Contains("runtime-v1"))throw new Exception("健康检查误认服务");checks.Add("real_http_fixture");
            }
            if(Connector.Healthy("http://127.0.0.1:1/api/v1/configuration"))throw new Exception("断线不应成功");checks.Add("connection_refused");
            var unrelated=Process.Start(new ProcessStartInfo(Application.ExecutablePath,"sleep"){UseShellExecute=false,CreateNoWindow=true});
            try {
                var owner=new Connector(Path.GetDirectoryName(Application.ExecutablePath),s=>{},CancellationToken.None);
                var method=typeof(Connector).GetMethod("Start",BindingFlags.Instance|BindingFlags.NonPublic);
                var child=(Process)method.Invoke(owner,new object[]{Application.ExecutablePath,"sleep",Path.GetDirectoryName(Application.ExecutablePath),null,false});
                int pid=child.Id;owner.Dispose();
                bool remains;try{Process.GetProcessById(pid);remains=true;}catch(ArgumentException){remains=false;}
                if(remains || unrelated.HasExited)throw new Exception("进程归属回收错误");checks.Add("dispose_only_owned_process");
            } finally {if(!unrelated.HasExited)unrelated.Kill();unrelated.WaitForExit();unrelated.Dispose();}
            var resolver=typeof(Connector).GetMethod("ResolveNode",BindingFlags.Public|BindingFlags.Static);
            if(resolver==null)throw new Exception("便携包缺少包内Node解析入口");
            string bundle=Path.Combine(Path.GetTempPath(),"造物便携 测试-"+Guid.NewGuid().ToString("N"));
            string nodeFolder=Path.Combine(bundle,"tools","node"),fallback=Path.Combine(bundle,"fallback");
            Directory.CreateDirectory(nodeFolder);Directory.CreateDirectory(fallback);
            string originalPath=Environment.GetEnvironmentVariable("PATH");
            try {
                string bundled=Path.Combine(nodeFolder,"node.exe"),system=Path.Combine(fallback,"node.exe");
                File.WriteAllText(bundled,"fixture");File.WriteAllText(system,"fixture");Environment.SetEnvironmentVariable("PATH",fallback);
                if((string)resolver.Invoke(null,new object[]{bundle})!=bundled)throw new Exception("没有优先选包内Node");checks.Add("portable_node_preferred");
                File.Delete(bundled);
                if((string)resolver.Invoke(null,new object[]{bundle})!=system)throw new Exception("系统Node兼容失败");checks.Add("system_node_fallback");
                Environment.SetEnvironmentVariable("PATH","");bool rejected=false;
                try{resolver.Invoke(null,new object[]{bundle});}catch(TargetInvocationException){rejected=true;}
                if(!rejected)throw new Exception("缺Node应明确失败");checks.Add("missing_node_rejected");
            } finally {
                Environment.SetEnvironmentVariable("PATH",originalPath);
                foreach(string file in Directory.GetFiles(nodeFolder))File.Delete(file);
                foreach(string file in Directory.GetFiles(fallback))File.Delete(file);
                Directory.Delete(nodeFolder);Directory.Delete(Path.Combine(bundle,"tools"));Directory.Delete(fallback);Directory.Delete(bundle);
            }
            Console.WriteLine(new JavaScriptSerializer().Serialize(new{passed=checks.Count,checks=checks,cloud_called=false,model_called=false}));return 0;
        } catch(Exception exc){Console.WriteLine(new JavaScriptSerializer().Serialize(new{error=exc.ToString(),checks=checks}));return 2;}
    }
}
