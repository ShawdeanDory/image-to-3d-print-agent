// 使用Windows自带.NET Framework构建；不包含账号、私钥或令牌。
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Net;
using System.Net.Sockets;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading;
using System.Threading.Tasks;
using System.Web.Script.Serialization;
using System.Windows.Forms;

public class LauncherConfig {
    public string ssh_config = "runtime/ssh/p2a_config";
    public string ssh_alias = "p2a-autodl";
    public string remote_project = "/root/autodl-tmp/image-to-3d-print-agent";
    public string deployment = "deployments/official-20261021-01";
    public int tunnel_port = 9000;
    public int ui_port = 5173;
    public void Validate() {
        if (!Regex.IsMatch(ssh_alias ?? "", @"\A[A-Za-z0-9_.-]+\z")) throw new Exception("SSH别名不合法");
        if (!Regex.IsMatch(remote_project ?? "", @"\A/[A-Za-z0-9_./-]+\z") || HasParent(remote_project)) throw new Exception("云端项目路径不合法");
        if (!Regex.IsMatch(deployment ?? "", @"\Adeployments/[A-Za-z0-9_./-]+\z") || HasParent(deployment)) throw new Exception("部署必须在deployments内");
        if (String.IsNullOrWhiteSpace(ssh_config) || Path.IsPathRooted(ssh_config) || HasParent(ssh_config.Replace('\\','/')) || ssh_config.Contains(":")) throw new Exception("SSH配置必须是项目内相对路径");
        if (ui_port < 1024 || ui_port > 65535 || tunnel_port < 1024 || tunnel_port > 65535 || ui_port == tunnel_port) throw new Exception("端口须在1024～65535且不能重复");
    }
    static bool HasParent(string value) { return Array.Exists(value.Split('/'), p => p == ".."); }
}

public class Connector : IDisposable {
    readonly string root;
    readonly Action<string> log;
    readonly CancellationToken token;
    readonly object gate = new object();
    readonly List<Process> owned = new List<Process>();
    bool disposed;
    public string Phase = "configuration";
    public string PageUrl;
    public LauncherConfig Config;
    public Connector(string directory, Action<string> output, CancellationToken cancellation) { root = directory; log = output; token = cancellation; }
    public static string Quote(string value) {
        var output = new StringBuilder("\"");int slashes=0;
        foreach(char c in value) {
            if(c=='\\') {slashes++;continue;}
            if(c=='"') {output.Append('\\',slashes*2+1);output.Append(c);}
            else {output.Append('\\',slashes);output.Append(c);}
            slashes=0;
        }
        output.Append('\\',slashes*2);output.Append('"');return output.ToString();
    }
    static string Args(params string[] values) { return String.Join(" ", Array.ConvertAll(values, Quote)); }
    static string Find(string name) {
        foreach(string part in (Environment.GetEnvironmentVariable("PATH") ?? "").Split(';')) {
            if (String.IsNullOrWhiteSpace(part)) continue;
            string candidate = Path.Combine(part.Trim('"'),name);
            if(File.Exists(candidate))return candidate;
        }
        throw new Exception("找不到"+name+"，请安装已有项目要求的Node.js或Windows OpenSSH，不会自动下载");
    }
    public static string ResolveNode(string directory) {
        string bundled=Path.Combine(directory,"tools","node","node.exe");
        return File.Exists(bundled)?bundled:Find("node.exe");
    }
    string Need(string relative) {
        string path=Path.GetFullPath(Path.Combine(root,relative));
        if(!path.StartsWith(root+Path.DirectorySeparatorChar,StringComparison.OrdinalIgnoreCase) || !File.Exists(path))throw new Exception("缺少项目文件："+relative);
        return path;
    }
    Process Start(string file,string arguments,string cwd, IDictionary<string,string> environment=null,bool input=false) {
        token.ThrowIfCancellationRequested();
        var info=new ProcessStartInfo(file,arguments) { WorkingDirectory=cwd,UseShellExecute=false,CreateNoWindow=true,
            RedirectStandardOutput=true,RedirectStandardError=true,RedirectStandardInput=input,StandardOutputEncoding=Encoding.UTF8,StandardErrorEncoding=Encoding.UTF8 };
        if(environment!=null)foreach(var pair in environment)info.EnvironmentVariables[pair.Key]=pair.Value;
        var process=new Process {StartInfo=info};
        lock(gate) { if(disposed)throw new OperationCanceledException();process.Start();owned.Add(process); }
        return process;
    }
    string RunSsh(string ssh,string sshConfig,string command,string source) {
        var process=Start(ssh,Args("-F",sshConfig,"-o","BatchMode=yes","-o","StrictHostKeyChecking=yes","-o","ConnectTimeout=8",Config.ssh_alias,command),root,null,true);
        var stdout=process.StandardOutput.ReadToEndAsync();var stderr=process.StandardError.ReadToEndAsync();
        byte[] bytes=Encoding.UTF8.GetBytes(source);process.StandardInput.BaseStream.Write(bytes,0,bytes.Length);process.StandardInput.Close();
        var deadline=DateTime.UtcNow.AddSeconds(70);
        while(!process.WaitForExit(100)) { token.ThrowIfCancellationRequested();if(DateTime.UtcNow>deadline)throw new Exception("云端服务准备超时，请查看启动日志"); }
        string text=stdout.Result;string error=stderr.Result;
        if(process.ExitCode!=0)throw new Exception("SSH/云端服务未就绪。请确认实例已开机、SSH地址/端口及公钥未变。\r\n"+text+error);
        return text;
    }
    public static string Get(string url) {
        var request=(HttpWebRequest)WebRequest.Create(url);request.Proxy=null;request.Timeout=2500;request.ReadWriteTimeout=2500;
        using(var response=request.GetResponse())using(var reader=new StreamReader(response.GetResponseStream(),Encoding.UTF8))return reader.ReadToEnd();
    }
    public static bool Healthy(string url) {
        try { var data=new JavaScriptSerializer().Deserialize<Dictionary<string,object>>(Get(url));return data.ContainsKey("schema_version") && (string)data["schema_version"]=="runtime-v1" && data.ContainsKey("configured_backends"); }
        catch {return false;}
    }
    static bool Listening(int port) { using(var client=new TcpClient())try {var result=client.BeginConnect("127.0.0.1",port,null,null);if(!result.AsyncWaitHandle.WaitOne(200))return false;client.EndConnect(result);return true;}catch{return false;} }
    void Wait(Func<bool> ready,Process process,string error,int seconds) {
        var end=DateTime.UtcNow.AddSeconds(seconds);
        while(!ready()) { token.ThrowIfCancellationRequested();if(process.HasExited)throw new Exception(error+"：进程已退出，请查看日志");if(DateTime.UtcNow>end)throw new Exception(error+"：等待超时");Thread.Sleep(250); }
    }
    void Drain(Process process,string prefix) {
        process.OutputDataReceived+=(s,e)=>{if(e.Data!=null)log(prefix+e.Data);};process.ErrorDataReceived+=(s,e)=>{if(e.Data!=null)log(prefix+e.Data);};
        process.BeginOutputReadLine();process.BeginErrorReadLine();
    }
    public void Connect() {
        Phase="configuration";
        string configFile=Path.Combine(root,"runtime/launcher/config.json");
        if(!File.Exists(configFile))configFile=Need("config/launcher.example.json");
        var json=new JavaScriptSerializer();string raw=File.ReadAllText(configFile,Encoding.UTF8);
        var fields=json.Deserialize<Dictionary<string,object>>(raw);
        foreach(string key in fields.Keys)if(!new List<string>{"ssh_config","ssh_alias","remote_project","deployment","tunnel_port","ui_port"}.Contains(key))throw new Exception("启动配置含未知字段："+key);
        Config=json.Deserialize<LauncherConfig>(raw);Config.Validate();PageUrl="http://127.0.0.1:"+Config.ui_port+"/";
        if(!File.Exists(Path.Combine(root,Config.ssh_config)) && File.Exists(Path.Combine(root,"首次配置.cmd")))
            throw new Exception("尚未配置SSH，请先双击“首次配置.cmd”，把生成的公钥交给组长授权后再启动。");
        string sshConfig=Need(Config.ssh_config);string helper=Need("scripts/desktop_launcher/ensure_cloud_service.py");
        string vite=Need("frontend/node_modules/vite/bin/vite.js");Need("frontend/dist/index.html");
        string ssh=Find("ssh.exe"),node=ResolveNode(root);
        log("检查通过：现有SSH配置、Node.js和网页文件均在，不读取或打包密钥。");
        Phase="cloud";log("1/3连接云端，检查并补启动API/单worker…");
        string command="'"+Config.remote_project+"/runtime/envs/backend/bin/python' - --project '"+Config.remote_project+"' --deployment '"+Config.deployment+"'";
        string output=RunSsh(ssh,sshConfig,command,File.ReadAllText(helper,Encoding.UTF8));
        var remote=json.Deserialize<Dictionary<string,object>>(output.Trim());
        if(!remote.ContainsKey("api") || !remote.ContainsKey("worker"))throw new Exception("云端启动检查没有返回完整服务结果");
        log("云端API："+remote["api"]+"；worker："+remote["worker"]+"。");
        Phase="tunnel";string api="http://127.0.0.1:"+Config.tunnel_port+"/api/v1/configuration";
        log("2/3建立本机安全隧道…");
        if(Listening(Config.tunnel_port)) { if(!Healthy(api))throw new Exception("本机"+Config.tunnel_port+"端口被占用或旧隧道已断开，请关闭旧连接或修改启动配置；不会终止其他进程");log("复用已就绪的本机隧道。"); }
        else {
            var tunnel=Start(ssh,Args("-F",sshConfig,"-o","BatchMode=yes","-o","StrictHostKeyChecking=yes","-o","ConnectTimeout=8","-o","ExitOnForwardFailure=yes","-o","ServerAliveInterval=15","-o","ServerAliveCountMax=3","-N","-L","127.0.0.1:"+Config.tunnel_port+":127.0.0.1:8000",Config.ssh_alias),root);
            Drain(tunnel,"SSH：");Wait(()=>Healthy(api),tunnel,"隧道未能连接真实API",20);
        }
        Phase="frontend";log("3/3启动网页并检查页面到计算服务的完整连接…");
        string pageApi=PageUrl+"api/v1/configuration";
        Func<bool> pageReady=()=>{try{return Get(PageUrl).Contains("造物工坊") && Healthy(pageApi);}catch{return false;}};
        if(Listening(Config.ui_port)) { if(!pageReady())throw new Exception("本机"+Config.ui_port+"网页端口已被其他服务/错误代理占用，请先关闭旧网页服务；不会强杀其他进程");log("复用现有网页服务。"); }
        else {
            var web=Start(node,Args(vite,"preview","--host","127.0.0.1","--port",Config.ui_port.ToString(),"--strictPort"),Path.Combine(root,"frontend"),new Dictionary<string,string>{{"I3D_API_TARGET","http://127.0.0.1:"+Config.tunnel_port}});
            Drain(web,"网页：");Wait(pageReady,web,"网页或API代理未就绪",20);
        }
        Phase="ready";log("已连接。点击“打开网页”即可使用；请保留启动器窗口。关闭本窗口只回收本次本机进程，不关闭云端实例。");
    }
    public void Dispose() { lock(gate) { disposed=true;foreach(var p in owned) {try{if(!p.HasExited)p.Kill();p.WaitForExit(3000);p.Dispose();}catch{} }owned.Clear(); } }
}

public class LauncherWindow : Form {
    readonly TextBox messages=new TextBox {Multiline=true,ReadOnly=true,ScrollBars=ScrollBars.Vertical,Dock=DockStyle.Fill};
    readonly Label state=new Label {Text="准备连接…",Dock=DockStyle.Top,Height=45,Padding=new Padding(10),Font=new Font("Microsoft YaHei UI",13)};
    readonly Button retry=new Button {Text="重新连接",Width=110};
    readonly Button open=new Button {Text="打开网页",Width=110,Enabled=false};
    readonly Button logs=new Button {Text="查看日志",Width=110};
    readonly string root,folder,logFile;
    Connector connector;CancellationTokenSource cancellation;bool busy,closing;
    readonly System.Windows.Forms.Timer monitor=new System.Windows.Forms.Timer {Interval=10000};
    public LauncherWindow(string directory) {
        root=directory;folder=Path.Combine(root,"runtime/launcher");Directory.CreateDirectory(folder);logFile=Path.Combine(folder,"launcher-"+DateTime.Now.ToString("yyyyMMdd-HHmmss")+".log");
        Text="造物工坊·启动与连接";Width=800;Height=530;StartPosition=FormStartPosition.CenterScreen;Font=new Font("Microsoft YaHei UI",10);
        var buttons=new FlowLayoutPanel {Dock=DockStyle.Bottom,Height=50,Padding=new Padding(8)};buttons.Controls.AddRange(new Control[]{retry,open,logs});Controls.Add(messages);Controls.Add(state);Controls.Add(buttons);
        retry.Click+=(s,e)=>Connect();open.Click+=(s,e)=>OpenPage();logs.Click+=(s,e)=>Process.Start("explorer.exe",folder);
        Shown+=(s,e)=>Connect();FormClosing+=(s,e)=>{closing=true;monitor.Stop();if(cancellation!=null)cancellation.Cancel();if(connector!=null)connector.Dispose();};
        monitor.Tick+=async(s,e)=>{if(busy||connector==null||connector.Phase!="ready")return;bool alive=await Task.Run(()=>Connector.Healthy(connector.PageUrl+"api/v1/configuration"));if(!closing)state.Text=alive?"已连接计算服务":"连接已断开，请点击重新连接；确认云端实例仍开机";};
    }
    void Log(string value) {
        if(closing)return;
        if(InvokeRequired){try{BeginInvoke(new Action<string>(Log),value);}catch{}return;}
        string line=DateTime.Now.ToString("HH:mm:ss")+" "+value+Environment.NewLine;messages.AppendText(line);File.AppendAllText(logFile,line,Encoding.UTF8);
    }
    async void Connect() {
        if(busy)return;busy=true;retry.Enabled=false;open.Enabled=false;monitor.Stop();state.Text="正在连接，请稍候…";
        if(connector!=null)connector.Dispose();if(cancellation!=null)cancellation.Dispose();cancellation=new CancellationTokenSource();connector=new Connector(root,Log,cancellation.Token);
        try {await Task.Run(()=>connector.Connect());if(closing)return;state.Text="已连接计算服务";open.Enabled=true;OpenPage();monitor.Start();}
        catch(Exception exc){if(!closing){state.Text="未能连接："+connector.Phase;Log(exc.Message);connector.Dispose();WriteResult(root,"failed",connector.Phase,null,exc.Message);}}
        finally{busy=false;if(!closing)retry.Enabled=true;}
    }
    void OpenPage(){if(connector!=null && connector.Phase=="ready"){Process.Start(new ProcessStartInfo(connector.PageUrl){UseShellExecute=true});WriteResult(root,"succeeded","ready",connector.PageUrl,null);}}
    public static void WriteResult(string directory,string status,string phase,string url,string error) {
        var value=new Dictionary<string,object>{{"kind","desktop_launcher"},{"status",status},{"phase",phase},{"page_url",url},{"model_submitted",false},{"error",error==null?null:new Dictionary<string,object>{{"code","TOOL_UNAVAILABLE"},{"message",error},{"details",new Dictionary<string,object>()}}}};
        string folder=Path.Combine(directory,"runtime/launcher");Directory.CreateDirectory(folder);File.WriteAllText(Path.Combine(folder,"last-result.json"),new JavaScriptSerializer().Serialize(value),new UTF8Encoding(false));
    }
}

public static class Program {
    [STAThread] public static int Main(string[] args) {
        string root=Path.GetDirectoryName(Application.ExecutablePath);
        if(args.Length>0 && args[0]=="--smoke") {
            try {using(var connector=new Connector(root,Console.WriteLine,CancellationToken.None)){connector.Connect();LauncherWindow.WriteResult(root,"succeeded",connector.Phase,connector.PageUrl,null);}return 0;}
            catch(Exception exc){LauncherWindow.WriteResult(root,"failed","smoke",null,exc.Message);return 2;}
        }
        bool fresh;using(var mutex=new Mutex(true,"Local\\I3DDesktopLauncher",out fresh)) {
            if(!fresh){MessageBox.Show("启动器已经运行。请在任务栏打开“造物工坊·启动与连接”，点击打开网页或重新连接。");return 0;}
            Application.EnableVisualStyles();Application.SetCompatibleTextRenderingDefault(false);Application.Run(new LauncherWindow(root));
        }
        return 0;
    }
}
