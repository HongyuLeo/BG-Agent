using System;
using System.Collections.Generic;
using System.IO;
using System.Text;
using Bgtracker.Msync;
namespace PublicRacesHelper {
sealed class FakeMemory : IMemory {
    readonly Dictionary<long,byte> data=new Dictionary<long,byte>();public Func<long,int,byte[]> Override;public bool Disposed;
    public void Put(long a,byte[] b){for(int i=0;i<b.Length;i++)data[a+i]=b[i];}
    public void I(long a,int n){Put(a,BitConverter.GetBytes(n));}public void P(long a,long n){Put(a,BitConverter.GetBytes(n));}
    public byte[] Read(long a,int n){if(Override!=null){var v=Override(a,n);if(v!=null)return v;}var b=new byte[n];for(int i=0;i<n;i++)if(data.ContainsKey(a+i))b[i]=data[a+i];return b;}
    public void Dispose(){Disposed=true;}
}
static class SelfTests {
    static int passed;static void Check(bool value,string name){if(!value)throw new Exception("FAIL: "+name);}
    static void Reject(Action action,string name){bool rejected=false;try{action();}catch(InvalidDataException){rejected=true;}catch(NotReadyException){rejected=true;}Check(rejected,name);}
    static long next=0x500000;
    static long Alloc(){long p=next;next+=0x4000;return p;}
    static long Class(FakeMemory m,string[] names,int[] offsets){long c=Alloc(),f=Alloc();m.Put(c+Off.ClassKind,new byte[]{1});m.P(c+Off.ClassFields,f);m.I(c+Off.ClassFieldCount,names.Length);for(int i=0;i<names.Length;i++){long s=Alloc();m.Put(s,Encoding.ASCII.GetBytes(names[i]+"\0"));m.P(f+i*32+8,s);m.I(f+i*32+24,offsets[i]);}return c;}
    static void Object(FakeMemory m,long instance,long cls){long v=Alloc();m.P(v,cls);m.P(instance,v);}
    static long List(FakeMemory m,int[] values,out long versionAddress){
        long cls=Class(m,new[]{"_items","_size","_version"},new[]{16,24,28}),list=Alloc(),array=Alloc();Object(m,list,cls);m.P(list+16,array);m.I(list+24,values.Length);m.I(list+28,7);m.I(array+24,16);for(int i=0;i<values.Length;i++)m.I(array+32+i*4,values[i]);versionAddress=list+28;return list;
    }
    static void ValidList(){using(var m=new FakeMemory()){long v;long list=List(m,new[]{11,17,126},out v);int version;int[] r=new Reader(m).Races(list,out version);Check(r.Length==3&&r[2]==126&&version==7,"public list enum order");ServiceAndConnection(m);SnapshotIdentity(m,list);}passed++;}
    static void SnapshotIdentity(FakeMemory m,long list){
        long cls=Class(m,new[]{"s_instance","m_gameEntity","m_availableRacesInBattlegroundsExcludingAmalgam","m_createGamePhase","m_gameOver"},new[]{0,16,24,32,36}),state=Alloc(),ri=Alloc(),vt=Alloc(),store=Alloc();Object(m,state,cls);m.P(cls+Off.ClassRuntimeInfo,ri);m.P(ri+8,vt);m.P(vt+Off.VTableData,store);m.P(store,state);m.I(cls+Off.ClassVTableSize,0);
        long ec=Class(m,new[]{"<Uuid>k__BackingField"},new[]{16}),entity=Alloc(),uuid=Alloc();Object(m,entity,ec);m.P(entity+16,uuid);m.I(uuid+16,7);m.Put(uuid+20,Encoding.Unicode.GetBytes("fixture"));m.P(state+16,entity);m.P(state+24,list);m.I(state+32,2);m.Put(state+36,new byte[]{0});
        var r=new Reader(m);var s=r.Snapshot(cls);Check((string)s["game_uuid"]=="fixture"&&(int)s["create_game_phase"]==2,"CREATED snapshot source identity");
        m.I(state+32,1);Reject(delegate{new Reader(m).Snapshot(cls);},"CREATING snapshot rejected");m.I(state+32,2);
        int reads=0;m.Override=delegate(long a,int n){if(a==state+16&&++reads==2)return BitConverter.GetBytes(entity+0x1000);return null;};Reject(delegate{new Reader(m).Snapshot(cls);},"GameEntity changed during read");m.Override=null;
    }
    static void ServiceAndConnection(FakeMemory m){
        long manager=Class(m,new[]{"s_runtimeServices","s_dynamicServices"},new[]{0,8}),ri=Alloc(),vt=Alloc(),store=Alloc();m.P(manager+Off.ClassRuntimeInfo,ri);m.P(ri+8,vt);m.I(manager+Off.ClassVTableSize,0);m.P(vt+Off.VTableData,store);
        long locatorClass=Class(m,new[]{"m_services"},new[]{16}),locator=Alloc();Object(m,locator,locatorClass);m.P(store,locator);
        long dictClass=Class(m,new[]{"_entries","_count","_version"},new[]{16,24,28}),dict=Alloc();Object(m,dict,dictClass);m.P(locator+16,dict);m.I(dict+24,1);m.I(dict+28,9);
        long entryClass=Class(m,new[]{"hashCode","value"},new[]{16,32}),arrayClass=Alloc(),array=Alloc();
        // Reproduce actual Mono field locations independently of Off constants:
        // boxed Entry size40 at+0x1c, array element stride24 at arrayClass+0x90.
        // Entry-class +0x90 is irrelevant garbage: the old v1 code read this.
        m.I(entryClass+28,40);m.I(entryClass+144,0);m.I(arrayClass+144,24);
        m.P(arrayClass,entryClass);Object(m,array,arrayClass);m.I(array+24,1);m.P(dict+16,array);m.I(array+32,44);
        long infoClass=Class(m,new[]{"<Service>k__BackingField"},new[]{16}),info=Alloc();Object(m,info,infoClass);m.P(array+48,info);
        long networkClass=Class(m,new[]{"m_state"},new[]{32}),network=Alloc();Object(m,network,networkClass);m.P(info+16,network);
        long stateClass=Class(m,new[]{"<LastGameServerInfo>k__BackingField"},new[]{40}),serverClass=Class(m,new[]{"<GameHandle>k__BackingField","<ClientHandle>k__BackingField"},new[]{16,24}),server=Alloc();Object(m,server,serverClass);m.P(network+32+24,server);m.I(server+16,30223);m.P(server+24,130382848);
        var r=new Reader(m);Check(r.NetworkService(manager,networkClass)==network,"exact Network service");var con=r.Connection(network,stateClass);Check(con[2]==30223&&con[3]==130382848,"public game/client handles from embedded value type");
        Reject(delegate{Reader.Bound(new Reader(m).Int(entryClass+144)-16,16,128,"service Entry stride");},"v1 literal144 reproduces invalid stride on actual-layout fixture");
        m.I(arrayClass+144,32);Reject(delegate{new Reader(m).NetworkService(manager,networkClass);},"inconsistent array/value stride rejected");m.I(arrayClass+144,24);
        m.I(entryClass+28,8);Reject(delegate{new Reader(m).NetworkService(manager,networkClass);},"bad boxed value size rejected");m.I(entryClass+28,40);
        m.P(server+24,0);Reject(delegate{r.Connection(network,stateClass);},"zero client handle not ready");
    }
    static void InvalidRaces(){foreach(var r in new[]{new int[0],new[]{0},new[]{26},new[]{999},new[]{11,11}})Reject(delegate{Reader.ValidateRaces(r);},"invalid race rejected");Check(!Reader.Pointer(0)&&!Reader.Pointer(0x800000000000L),"pointer limits");passed++;}
    static void ListChanged(){using(var m=new FakeMemory()){long v;long list=List(m,new[]{14,20},out v);int hits=0;m.Override=delegate(long a,int n){if(a==v&&++hits==2)return BitConverter.GetBytes(8);return null;};Reject(delegate{int ver;new Reader(m).Races(list,out ver);},"list mutation rejected");}passed++;}
    static void BadCountAndCycle(){using(var m=new FakeMemory()){long v;long list=List(m,new[]{14},out v);m.I(list+24,12);Reject(delegate{int ver;new Reader(m).Races(list,out ver);},"oversized list rejected before payload");long image=Alloc(),table=Alloc(),cls=Class(m,new string[0],new int[0]),name=Alloc(),ns=Alloc();m.Put(name,Encoding.ASCII.GetBytes("Other\0"));m.Put(ns,new byte[]{0});m.P(cls+Off.ClassName,name);m.P(cls+Off.ClassNamespace,ns);m.P(cls+Off.ClassNextInCache,cls);m.I(image+Off.ImageClassCache+Off.HashTableSize,1);m.P(image+Off.ImageClassCache+Off.HashTableTable,table);m.P(table,cls);Reject(delegate{new Reader(m).FindClass(image,"GameState");},"class cycle bounded");}passed++;}
    static void RootMachineCode(){using(var m=new FakeMemory()){
        long b=0x100000;int size=0x10000;m.Put(b,new byte[]{0x4d,0x5a});m.I(b+0x3c,0x100);m.I(b+0x100,0x4550);m.Put(b+0x118,new byte[]{0x0b,0x02});m.I(b+0x188,0x1000);m.I(b+0x18c,0x100);m.I(b+0x1014,2);m.I(b+0x1018,1);m.I(b+0x101c,0x2000);m.I(b+0x1020,0x2100);m.I(b+0x1024,0x2200);m.I(b+0x2100,0x2300);m.Put(b+0x2300,Encoding.ASCII.GetBytes("mono_get_root_domain\0"));m.Put(b+0x2200,new byte[]{1,0});m.I(b+0x2004,0x3000);m.Put(b+0x3000,new byte[]{0x48,0x8b,0x05,0,0,0,0,0xc3});m.I(b+0x3003,0x4000-0x3007);m.P(b+0x4000,0x900000);Check(new Reader(m).RootDomain(b,size)==0x900000,"PE named ordinal resolution");m.Put(b+0x3000,new byte[]{0x90});Reject(delegate{new Reader(m).RootDomain(b,size);},"unsupported root machine code rejected");
    }passed++;}
    public static int Run(){try{ValidList();InvalidRaces();ListChanged();BadCountAndCycle();RootMachineCode();Console.WriteLine("{\"ok\":true,\"test_source\":\"fake_memory_only\",\"tests_passed\":"+passed+"}");return 0;}catch(Exception e){Console.WriteLine("{\"ok\":false,\"error\":\""+e.Message.Replace("\"","'")+"\"}");return 1;}}
}
}
