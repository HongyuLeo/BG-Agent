// Mono structure traversal adapted from BattlegroundsHelp/bgtracker Mono.cs (MIT).
// Copyright (c) 2026 the bgtracker contributors. See LICENSE and ATTRIBUTION.txt.
// This executable never invokes Mono functions or writes into the target process.
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text;
using System.Web.Script.Serialization;
using Bgtracker.Msync;

namespace PublicRacesHelper {
sealed class NotReadyException : Exception {public NotReadyException(string message):base(message){}}
interface IMemory : IDisposable { byte[] Read(long address, int count); }
sealed class NativeMemory : IMemory {
    [DllImport("kernel32.dll", SetLastError=true)] static extern IntPtr OpenProcess(uint access, bool inherit, int pid);
    [DllImport("kernel32.dll", SetLastError=true)] static extern bool CloseHandle(IntPtr handle);
    [DllImport("kernel32.dll", SetLastError=true)] static extern bool ReadProcessMemory(IntPtr handle, IntPtr address, byte[] bytes, IntPtr count, out IntPtr read);
    IntPtr handle;
    public NativeMemory(int pid) { handle=OpenProcess(0x0010|0x0400,false,pid); if(handle==IntPtr.Zero) throw new InvalidOperationException("OpenProcess READ|QUERY failed: "+Marshal.GetLastWin32Error()); }
    public byte[] Read(long address,int count) {
        if(handle==IntPtr.Zero) throw new ObjectDisposedException("NativeMemory");
        var data=new byte[count]; IntPtr got;
        if(!ReadProcessMemory(handle,new IntPtr(address),data,new IntPtr(count),out got)||got.ToInt64()!=count) throw new NotReadyException("ReadProcessMemory failed or short read");
        return data;
    }
    public void Dispose(){ if(handle!=IntPtr.Zero){CloseHandle(handle);handle=IntPtr.Zero;} }
}
sealed class Reader {
    readonly IMemory mem; int calls; long bytes;
    public Reader(IMemory mem){this.mem=mem;}
    public static bool Pointer(long p){return p>=0x10000 && p<0x0000800000000000L;}
    public byte[] Read(long p,int n){
        if(!Pointer(p)||n<1||n>1048576||p+n>=0x0000800000000000L) throw new InvalidDataException("Invalid address/read size");
        if(++calls>1000000 || (bytes+=n)>67108864) throw new InvalidDataException("Read budget exceeded");
        return mem.Read(p,n);
    }
    public long Ptr(long p){long v=BitConverter.ToInt64(Read(p,8),0);if(v!=0&&!Pointer(v))throw new InvalidDataException("Invalid pointer");return v;}
    public int Int(long p){return BitConverter.ToInt32(Read(p,4),0);}
    public string CString(long p,int max){
        if(!Pointer(p)||max<1||max>512)throw new InvalidDataException("Invalid string pointer/limit");
        var b=Read(p,max);int end=Array.IndexOf(b,(byte)0);if(end<0)throw new InvalidDataException("Unterminated metadata string");
        for(int i=0;i<end;i++)if(b[i]<32||b[i]>126)throw new InvalidDataException("Non-ASCII metadata name");
        return Encoding.ASCII.GetString(b,0,end);
    }
    public string MonoString(long p){
        if(p==0)return null;int n=Int(p+16);if(n<0||n>128)throw new InvalidDataException("Invalid managed string length");
        return n==0?"":Encoding.Unicode.GetString(Read(p+20,n*2));
    }
    public static int Bound(int value,int min,int max,string name){if(value<min||value>max)throw new InvalidDataException("Invalid "+name);return value;}
    long InModule(long b,int size,int rva,int needed){ if(rva<0||needed<0||(long)rva+needed>size)throw new InvalidDataException("PE RVA outside module");return b+rva; }
    public long RootDomain(long b,int size){
        if(BitConverter.ToUInt16(Read(b,2),0)!=0x5a4d)throw new InvalidDataException("Missing MZ");
        int pe=Int(b+0x3c);long ph=InModule(b,size,pe,0x90);
        if(Int(ph)!=0x4550||BitConverter.ToUInt16(Read(ph+24,2),0)!=0x20b)throw new InvalidDataException("Not PE32+");
        int ex=Int(ph+0x88),exSize=Int(ph+0x8c);long ep=InModule(b,size,ex,40);
        int funcs=Bound(Int(ep+20),1,65536,"PE function count"), names=Bound(Int(ep+24),1,65536,"PE name count");
        int fa=Int(ep+28),na=Int(ep+32),oa=Int(ep+36);
        InModule(b,size,fa,checked(funcs*4));InModule(b,size,na,checked(names*4));InModule(b,size,oa,checked(names*2));
        for(int i=0;i<names;i++){
            int nr=Int(b+na+i*4);string name=CString(InModule(b,size,nr,64),64);
            if(name!="mono_get_root_domain")continue;
            int ordinal=BitConverter.ToUInt16(Read(b+oa+i*2,2),0);if(ordinal>=funcs)throw new InvalidDataException("PE ordinal out of bounds");
            int fr=Int(b+fa+ordinal*4);if(fr>=ex&&(long)fr<ex+(long)exSize)throw new InvalidDataException("Forwarded export unsupported");
            long fn=InModule(b,size,fr,8);byte[] code=Read(fn,8);
            if(code[0]!=0x48||code[1]!=0x8b||code[2]!=0x05||code[7]!=0xc3)throw new InvalidDataException("Unsupported mono_get_root_domain machine code");
            long global=fn+7+BitConverter.ToInt32(code,3);
            if(global<b||global+8>b+size)throw new InvalidDataException("Root domain slot outside Mono module");
            long domain=Ptr(global);if(domain==0)throw new InvalidDataException("No root domain");return domain;
        }
        throw new InvalidDataException("mono_get_root_domain export absent");
    }
    public long Image(long domain){return Image(domain,"Assembly-CSharp");}
    public long Image(long domain,string assembly){
        var visited=new HashSet<long>();long node=Ptr(domain+Off.DomainAssemblies);
        for(int i=0;node!=0;i++){
            if(i>=512||!visited.Add(node))throw new InvalidDataException("Assembly chain exceeds limit or cycles");
            long a=Ptr(node),name=Ptr(a+16);
            if(CString(name,128)==assembly)return Ptr(a+Off.AssemblyImage);
            node=Ptr(node+8);
        }
        throw new NotReadyException("Required assembly not loaded: "+assembly);
    }
    public long FindClass(long image,string name){return FindClass(image,"",name);}
    public long FindClass(long image,string ns,string name){
        long cache=image+Off.ImageClassCache;int count=Bound(Int(cache+Off.HashTableSize),1,65536,"class buckets");long table=Ptr(cache+Off.HashTableTable);
        var visited=new HashSet<long>();int total=0;
        for(int b=0;b<count;b++){
            long c=Ptr(table+b*8L);int chain=0;
            while(c!=0){
                if(++chain>512||++total>200000||!visited.Add(c))throw new InvalidDataException("Class cache cycles or exceeds limit");
                if(CString(Ptr(c+Off.ClassName),128)==name&&CString(Ptr(c+Off.ClassNamespace),128)==ns)return c;
                c=Ptr(c+Off.ClassNextInCache);
            }
        }
        throw new InvalidDataException("Required class absent: "+name);
    }
    long Holding(long c){int kind=Read(c+Off.ClassKind,1)[0]&7;if(kind!=3)return c;long generic=Ptr(c+Off.ClassGenericClass);if(generic==0)throw new InvalidDataException("Missing generic definition");return Ptr(generic);}
    public int Offset(long cls,string field,bool inherited){
        var seen=new HashSet<long>();
        for(int depth=0;cls!=0;depth++){
            if(depth>=32||!seen.Add(cls))throw new InvalidDataException("Class parent cycles or exceeds limit");
            long c=Holding(cls),fields=Ptr(c+Off.ClassFields);int n=Bound(Int(c+Off.ClassFieldCount),0,4096,"field count");
            if(n>0&&fields==0)throw new InvalidDataException("Missing field array");
            for(int i=0;i<n;i++)if(CString(Ptr(fields+i*(long)Off.FieldSize+Off.FieldName),128)==field)return Bound(Int(fields+i*(long)Off.FieldSize+Off.FieldOffsetValue),0,1048576,"field offset");
            if(!inherited)break;cls=Ptr(c+Off.ClassParent);
        }
        throw new InvalidDataException("Required field absent: "+field);
    }
    public long ClassOf(long instance){long v=Ptr(instance);if(v==0)throw new InvalidDataException("Missing vtable");long c=Ptr(v);if(c==0)throw new InvalidDataException("Missing class");return c;}
    public long Ref(long instance,string field){return Ptr(instance+Offset(ClassOf(instance),field,true));}
    public int Integer(long instance,string field){return Int(instance+Offset(ClassOf(instance),field,true));}
    public int Byte(long instance,string field){return Read(instance+Offset(ClassOf(instance),field,true),1)[0];}
    public long StaticRef(long cls,string field){
        int off=Offset(cls,field,false),size=Bound(Int(cls+Off.ClassVTableSize),0,65536,"vtable size");
        long ri=Ptr(cls+Off.ClassRuntimeInfo);if(ri==0)throw new NotReadyException("Class runtime info not ready");
        long vt=Ptr(ri+Off.RuntimeInfoDomainVtables);if(vt==0)throw new NotReadyException("Class vtable not ready");
        long store=Ptr(vt+Off.VTableData+8L*size);if(store==0)throw new NotReadyException("Static store not ready");return Ptr(store+off);
    }
    public long Singleton(long cls){
        long obj=StaticRef(cls,"s_instance");if(obj==0)throw new NotReadyException("No active GameState singleton");
        if(ClassOf(obj)!=cls)throw new InvalidDataException("GameState singleton class mismatch");return obj;
    }
    public static readonly HashSet<int> AllowedRaces=new HashSet<int>{11,14,15,17,18,20,23,24,43,92,126};
    public static void ValidateRaces(int[] races){
        if(races==null||races.Length<1||races.Length>11)throw new InvalidDataException("Empty/oversized public races");
        var seen=new HashSet<int>();foreach(int race in races)if(!AllowedRaces.Contains(race)||!seen.Add(race))throw new InvalidDataException("INVALID/unknown/duplicate race");
    }
    public int[] Races(long list,out int version){
        if(list==0)throw new NotReadyException("Public race list absent");
        if(Integer(list,"_size")==0)throw new NotReadyException("Public race list not populated");
        int count=Bound(Integer(list,"_size"),1,11,"public race list size");version=Integer(list,"_version");long array=Ref(list,"_items");
        int capacity=Bound(Int(array+24),count,128,"race array capacity");
        var data=Read(array+32,count*4);var result=new int[count];for(int i=0;i<count;i++)result[i]=BitConverter.ToInt32(data,i*4);
        ValidateRaces(result);
        if(Integer(list,"_version")!=version||Integer(list,"_size")!=count||Ref(list,"_items")!=array)throw new NotReadyException("Public list changed during read");
        return result;
    }
    public Dictionary<string,object> Snapshot(long cls){
        long state=Singleton(cls),entity=Ref(state,"m_gameEntity");if(entity==0)throw new NotReadyException("No current public GameEntity");
        long list=Ref(state,"m_availableRacesInBattlegroundsExcludingAmalgam");int version;int[] races=Races(list,out version);
        string uuid=MonoString(Ref(entity,"<Uuid>k__BackingField"));int phase=Integer(state,"m_createGamePhase"),over=Byte(state,"m_gameOver");
        if(phase<0||phase>2)throw new InvalidDataException("Unknown CreateGamePhase");if(phase!=2)throw new NotReadyException("CreateGamePhase is not CREATED");
        if(over>1)throw new InvalidDataException("Invalid game-over Boolean");if(over!=0)throw new NotReadyException("Game is already over");
        if(Singleton(cls)!=state||Ref(state,"m_gameEntity")!=entity||Ref(state,"m_availableRacesInBattlegroundsExcludingAmalgam")!=list||Integer(list,"_version")!=version||Integer(state,"m_createGamePhase")!=phase||Byte(state,"m_gameOver")!=over||MonoString(Ref(entity,"<Uuid>k__BackingField"))!=uuid)throw new NotReadyException("Game changed during read");
        return new Dictionary<string,object>{{"game_state_id",Hex(state)},{"game_entity_id",Hex(entity)},{"game_entity_instance_id",Hex(entity)},{"game_entity_id_kind","instance_pointer_not_network_entity_id"},{"game_uuid",uuid},{"create_game_phase",phase},{"game_over",false},{"race_ids",races},{"source_field","GameState.s_instance.m_availableRacesInBattlegroundsExcludingAmalgam"},{"race_list_version",version}};
    }
    int Either(long cls,string first,string second){try{return Offset(cls,first,true);}catch(InvalidDataException ex){if(!ex.Message.StartsWith("Required field absent:"))throw;return Offset(cls,second,true);}}
    public long NetworkService(long manager,long networkClass){
        long locator=StaticRef(manager,"s_runtimeServices");
        if(locator==0){long dynamic=StaticRef(manager,"s_dynamicServices");if(dynamic==0)throw new NotReadyException("Service locator not ready");locator=Ref(dynamic,"m_serviceLocator");}
        if(locator==0)throw new NotReadyException("Service locator absent");
        long dict=Ref(locator,"m_services"),dc=ClassOf(dict);
        int countOff=Either(dc,"_count","count"),versionOff=Either(dc,"_version","version"),entriesOff=Either(dc,"_entries","entries");
        int count=Bound(Int(dict+countOff),0,1024,"service dictionary count"),version=Int(dict+versionOff);long entries=Ptr(dict+entriesOff);
        if(count==0||entries==0)throw new NotReadyException("Service dictionary not populated");
        int length=Bound(Int(entries+24),count,4096,"service dictionary capacity");
        // Both offsets and the -16 unboxing adjustment are confirmed by current
        // installed Mono's on-disk exports (never invoke remote functions).
        // Array class +0x00 is element_class; +0x90 is array element_size.
        // Element value class +0x1c is boxed instance_size, NOT +0x90.
        long arrayClass=ClassOf(entries),entryClass=Ptr(arrayClass);
        int stride=Bound(Int(arrayClass+Off.ClassArrayElementSize),16,128,"service array Entry stride");
        int unboxed=Bound(Int(entryClass+Off.ClassInstanceSize)-16,16,128,"service value Entry stride");
        if(stride!=unboxed)throw new InvalidDataException("Service Entry array/value size mismatch");
        int valueOff=Offset(entryClass,"value",true)-16,hashOff=Offset(entryClass,"hashCode",true)-16;
        if(stride%8!=0||valueOff<0||valueOff+8>stride||hashOff<0||hashOff+4>stride)throw new InvalidDataException("Unsupported dictionary Entry layout");
        long found=0;
        for(int i=0;i<count;i++){
            long cell=entries+32+i*(long)stride;if(Int(cell+hashOff)<0)continue;
            long info=Ptr(cell+valueOff);if(info==0)continue;
            long service=Ref(info,"<Service>k__BackingField");if(service==0)continue;
            if(ClassOf(service)==networkClass){if(found!=0)throw new InvalidDataException("Duplicate Network services");found=service;}
        }
        if(Int(dict+versionOff)!=version||Int(dict+countOff)!=count||Ptr(dict+entriesOff)!=entries)throw new NotReadyException("Service dictionary changed during read");
        if(found==0)throw new NotReadyException("Network service not ready");return found;
    }
    public long[] Connection(long network,long stateClass){
        // NetworkState is a VALUE TYPE inside Network, not an object pointer.
        long state=network+Offset(ClassOf(network),"m_state",true);
        int field=Offset(stateClass,"<LastGameServerInfo>k__BackingField",false)-16;
        if(field<0)throw new InvalidDataException("Unsupported NetworkState value layout");
        long info=Ptr(state+field);if(info==0)throw new NotReadyException("No last connected game server");
        long game=(uint)Integer(info,"<GameHandle>k__BackingField");
        long client=BitConverter.ToInt64(Read(info+Offset(ClassOf(info),"<ClientHandle>k__BackingField",true),8),0);
        if(game<=0||client<=0)throw new NotReadyException("Public connection handles not ready");
        return new[]{network,info,game,client};
    }
    static string Hex(long n){return "0x"+n.ToString("X");}
}
static class Program {
    const string Build="255790";
    const string AssemblySha="2408c5eae3d5ab083b8b290a7278147159e79a3c6e72e1d922ef44028ed16afb";
    const string MonoSha="86a5a4de6bcd74a637d63c96d822dc989d4ffaed6ef1c15c0e6e1f528ae6708f";
    static string Hash(string path){using(var h=SHA256.Create())using(var f=File.OpenRead(path))return BitConverter.ToString(h.ComputeHash(f)).Replace("-","").ToLowerInvariant();}
    static Dictionary<string,string> Args(string[] args){var d=new Dictionary<string,string>();for(int i=0;i<args.Length;i+=2){if(i+1>=args.Length||!args[i].StartsWith("--")||d.ContainsKey(args[i]))throw new ArgumentException("Expected unique --name value arguments");d.Add(args[i],args[i+1]);}foreach(string k in d.Keys)if(k!="--pid"&&k!="--expected-exe"&&k!="--expected-build"&&k!="--expected-start-ticks")throw new ArgumentException("Unknown argument: "+k);return d;}
    static string Required(Dictionary<string,string>d,string key){if(!d.ContainsKey(key)||String.IsNullOrWhiteSpace(d[key]))throw new ArgumentException("Required "+key);return d[key];}
    public static int Main(string[] args){
        var output=new Dictionary<string,object>{{"ok",false}};
        try{
            if(args.Length==1&&args[0]=="--self-test")return SelfTests.Run();
            if(IntPtr.Size!=8)throw new InvalidOperationException("x64 required");
            var d=Args(args);int pid=Int32.Parse(Required(d,"--pid"));long ticks=Int64.Parse(Required(d,"--expected-start-ticks"));
            string exe=Path.GetFullPath(Required(d,"--expected-exe")),build=Required(d,"--expected-build");
            if(build!=Build||pid<=0||ticks<=0||!String.Equals(Path.GetFileName(exe),"Hearthstone.exe",StringComparison.OrdinalIgnoreCase))throw new ArgumentException("Unsupported build/process identity");
            output["pid"]=pid;
            string root=Path.GetDirectoryName(exe),assembly=Path.Combine(root,"Hearthstone_Data","Managed","Assembly-CSharp.dll");
            if(Hash(assembly)!=AssemblySha)throw new InvalidDataException("Pinned 255790 Assembly-CSharp hash mismatch");
            if(Hash(Path.Combine(root,"Hearthstone_Data","Managed","Blizzard.T5.ServiceLocator.dll"))!="0c863df352c4091c856ad2b1da44c25526be3a6c02ea0ec68e047ae4724573be"||Hash(Path.Combine(root,"Hearthstone_Data","Managed","blizzard.bgsclient.dll"))!="457ba351f6373c9b9e2f14accdd87360832ad82a1278a9914025ab9ac7afc67d")throw new InvalidDataException("Pinned public connection metadata hash mismatch");
            string dbPath=Path.Combine(root,".product.db");if(new FileInfo(dbPath).Length>1048576)throw new InvalidDataException("Product metadata size limit");byte[] db=File.ReadAllBytes(dbPath);if(db.Length>1048576||Encoding.UTF8.GetString(db).IndexOf("37.0.0.255790",StringComparison.Ordinal)<0)throw new InvalidDataException("Installed product build255790 not proved");
            using(var game=Process.GetProcessById(pid)){
                if(game.StartTime.ToUniversalTime().Ticks!=ticks||!String.Equals(Path.GetFullPath(game.MainModule.FileName),exe,StringComparison.OrdinalIgnoreCase))throw new InvalidDataException("Process path/start identity mismatch");
                ProcessModule mono=null;foreach(ProcessModule m in game.Modules)if(String.Equals(m.ModuleName,"mono-2.0-bdwgc.dll",StringComparison.OrdinalIgnoreCase)){if(mono!=null)throw new InvalidDataException("Duplicate Mono modules");mono=m;}
                if(mono==null)throw new InvalidDataException("Mono runtime module missing");
                if(Hash(mono.FileName)!=MonoSha)throw new InvalidDataException("Pinned Mono runtime layout hash mismatch");
                using(var mem=new NativeMemory(pid)){
                    var r=new Reader(mem);long domain=r.RootDomain(mono.BaseAddress.ToInt64(),mono.ModuleMemorySize),image=r.Image(domain);long cls=r.FindClass(image,"GameState");
                    long services=r.Image(domain,"Blizzard.T5.ServiceLocator"),manager=r.FindClass(services,"Blizzard.T5.Services","ServiceManager"),networkClass=r.FindClass(image,"Network"),stateClass=r.FindClass(image,"NetworkState");
                    long network=r.NetworkService(manager,networkClass);long[] before=r.Connection(network,stateClass);
                    output=r.Snapshot(cls);long[] after=r.Connection(r.NetworkService(manager,networkClass),stateClass);
                    for(int i=0;i<before.Length;i++)if(before[i]!=after[i])throw new NotReadyException("Public connection changed during read");
                    var final=r.Snapshot(cls);foreach(string field in new[]{"game_state_id","game_entity_id","game_uuid","create_game_phase","race_list_version"})if(!Object.Equals(output[field],final[field]))throw new NotReadyException("Game identity changed after connection check");
                    int[] initialRaces=(int[])output["race_ids"],finalRaces=(int[])final["race_ids"];if(initialRaces.Length!=finalRaces.Length)throw new NotReadyException("Races changed after connection check");for(int i=0;i<initialRaces.Length;i++)if(initialRaces[i]!=finalRaces[i])throw new NotReadyException("Races changed after connection check");
                    output["network_game_id"]=before[2];output["network_client_id"]=before[3];output["network_source_field"]="Network.m_state.LastGameServerInfo.GameHandle/ClientHandle";
                    game.Refresh();if(game.HasExited||game.StartTime.ToUniversalTime().Ticks!=ticks)throw new InvalidDataException("Process exited/replaced");
                    output["ok"]=true;output["pid"]=pid;output["process_start_ticks"]=ticks;output["client_build"]=Build;output["source_assembly_sha256"]=AssemblySha;
                }
            }
            Console.WriteLine(new JavaScriptSerializer().Serialize(output));return 0;
        }catch(Exception ex){output=new Dictionary<string,object>{{"ok",false},{"retryable",ex is NotReadyException},{"error",ex.GetType().Name+": "+ex.Message}};Console.WriteLine(new JavaScriptSerializer().Serialize(output));return 2;}
    }
}
}
