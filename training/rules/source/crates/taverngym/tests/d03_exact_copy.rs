//! D03 unit/controlled-mechanism tests. Not a natural game producer claim.
use taverngym::{Game, RulesConfig};
use taverngym::cards::{cid,db};
use taverngym::content::buff_deity;
use taverngym::engine::Ctx;
use taverngym::state::{DeityState,Minion};
use taverngym::script::{script,Me};
use taverngym::event::Event;
use taverngym::types::{Kw,Races};

fn body(eid:u32,id:&str)->Minion { let mut m=Minion::new(eid,cid(id));m.set_stats(20,30);m }
fn setup(id:&str)->Game {
    let mut g=Game::new(0,RulesConfig {num_players:2,..RulesConfig::default()});
    g.players[0].deity=Some(DeityState {card:cid(id),atk:20,hp:30,golden:false,reborn:false});
    g
}
fn canonical(c:&Ctx)->(i32,i32) {let d=c.player_ref(0).unwrap().deity.as_ref().unwrap();(d.atk,d.hp)}
fn stats(c:&Ctx,eid:u32)->(i32,i32) {let m=c.minion(eid).unwrap();(m.atk,m.max_hp)}

#[test]
fn d03_normal_and_golden_copies_each_grow_once() {
    let mut g=setup("BGFYM_000");
    let mut c=Ctx::new(&mut g,[vec![body(101,"BGFYM_000"),body(102,"BGFYM_000_G")],vec![]],[Some(0),Some(1)],true);
    c.cs[0].deity_eid=101;
    buff_deity(&mut c,0,2,1);
    assert_eq!(canonical(&c),(22,31));assert_eq!(stats(&c,101),(22,31));assert_eq!(stats(&c,102),(22,31));
}

#[test]
fn d03_real_deities_exact_normal_gold_relationships_only() {
    assert_eq!(taverngym::flow::DEITIES,["BGFYM_000","BGFYM_011"]);
    for (id,other) in [("BGFYM_000","BGFYM_011"),("BGFYM_011","BGFYM_000")] {
        let gold=db().golden_of(cid(id));assert_eq!(db().normal_of(gold),cid(id));
        let mut g=setup(id);let mut golden=body(102,id);golden.card=gold;golden.golden=true;
        let mut c=Ctx::new(&mut g,[vec![body(101,id),golden,body(103,other),body(104,"BGFYM_005"),body(105,"BGFYM_002t")],vec![body(106,id)]],[Some(0),Some(1)],true);
        // Deliberately share the race: race membership is not the identity contract.
        for m in &mut c.boards[0] {m.races=Races::ABERRATION;}
        buff_deity(&mut c,0,2,1);
        for e in [101,102] {assert_eq!(stats(&c,e),(22,31));}
        for e in [103,104,105,106] {assert_eq!(stats(&c,e),(20,30));}
        assert_eq!(canonical(&c),(22,31));
    }
}

#[test]
fn d03_dead_destroyed_removed_and_opponent_are_not_targets() {
    let mut g=setup("BGFYM_000");let mut dead=body(101,"BGFYM_000");dead.hp=0;
    let mut destroyed=body(102,"BGFYM_000");destroyed.destroyed=true;
    let mut c=Ctx::new(&mut g,[vec![dead,destroyed,body(103,"BGFYM_000")],vec![body(104,"BGFYM_000")]],[Some(0),Some(1)],true);
    let removed=c.boards[0].remove(2);c.cs[0].deity_eid=removed.eid;
    buff_deity(&mut c,0,2,1);
    assert_eq!((removed.atk,removed.max_hp),(20,30));
    for e in [101,102,104] {assert_eq!(stats(&c,e),(20,30));}
    assert_eq!(canonical(&c),(22,31));
}

#[test]
fn d03_repeated_growth_and_copy_state_are_exact() {
    let mut g=setup("BGFYM_011");
    let mut c=Ctx::new(&mut g,[vec![body(101,"BGFYM_011"),body(102,"BGFYM_011")],vec![]],[Some(0),Some(1)],true);
    for _ in 0..2 {buff_deity(&mut c,0,4,2);}
    assert_eq!(canonical(&c),(28,34));
    for e in [101,102] {assert_eq!(stats(&c,e),(28,34));}
    let original=c.minion(101).unwrap().clone();let copy=c.full_copy(&original);
    assert_eq!((copy.atk,copy.max_hp),(28,34));
}

#[test]
fn d03_recruit_does_not_extend_body_growth_contract() {
    let mut g=setup("BGFYM_000");
    let mut c=Ctx::new(&mut g,[vec![body(101,"BGFYM_000")],vec![]],[Some(0),Some(1)],false);
    buff_deity(&mut c,0,2,1);assert_eq!(canonical(&c),(22,31));assert_eq!(stats(&c,101),(20,30));
}

#[test]
fn d03_sha_does_not_double_buff_any_deity_copy() {
    let mut g=setup("BGFYM_000");
    let mut c=Ctx::new(&mut g,[vec![body(101,"BGFYM_000"),body(102,"BGFYM_000_G"),body(103,"BG36_111")],vec![]],[Some(0),Some(1)],true);
    c.cs[0].deity_eid=101;
    let me=Me {side:0,eid:103,card:cid("BG36_111"),golden:false,opt:0,pos:2,data:0};
    let event=Event::SpellCast {side:0,card:cid("BG28_168"),target:0,tavern:true,data:0,opt:0};
    script(me.card).unwrap().on_event.unwrap()(&mut c,me,&event);
    assert_eq!(canonical(&c),(23,33));for e in [101,102,103] {assert_eq!(stats(&c,e),(23,33));}
}

#[test]
fn d03_reborn_body_growth_preserves_current_health_damage() {
    let mut g=setup("BGFYM_000");let mut dead=body(101,"BGFYM_000");dead.give(Kw::REBORN);dead.hp=0;
    let mut c=Ctx::new(&mut g,[vec![dead,body(102,"BGFYM_000")],vec![]],[Some(0),Some(1)],true);
    c.cs[0].deity_eid=101;c.resolve_deaths();
    let eid=c.cs[0].deity_eid;assert_ne!(eid,101);let before=c.minion(eid).unwrap().clone();assert_eq!(before.hp,1);
    buff_deity(&mut c,0,2,1);let after=c.minion(eid).unwrap();
    assert_eq!(after.hp,before.hp+1);assert_eq!(after.max_hp,before.max_hp+1);assert_eq!(stats(&c,102),(22,31));
}
