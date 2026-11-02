//! Controlled six-identity W2 contract; no natural-offer or pool qualification claim.
use taverngym::{Action, Game, RulesConfig};
use taverngym::cards::{cid, db};
use taverngym::engine::Ctx;
use taverngym::event::{Event, PlayInfo, ev};
use taverngym::script::{script, Me};
use taverngym::state::{Item, Minion, Pending, ShopSlot};
use taverngym::types::{Kw, Races};

fn game() -> Game {
    let mut g=Game::new(541, RulesConfig{num_players:2, triple_copies:99, ..RulesConfig::default()});
    for p in 0..2 {g.apply(p,Action::Choose(0)).unwrap();}
    for p in &mut g.players {
        p.pending.clear(); p.hand.clear(); p.board.clear(); p.shop.clear(); p.powers.clear();
        p.effects.clear(); p.quests.clear(); p.trinkets.clear(); p.counters.clear();
        p.stats=Default::default(); p.gold=10; p.tier=6; p.skipping=false;
    }
    g.next_eid=1000; g
}
fn m(eid:u32,id:&str)->Minion {Minion::new(eid,cid(id))}
fn body(eid:u32,races:Races)->Minion {let mut x=m(eid,"BG23_000");x.races=races;x.set_stats(10,10);x}
fn stats(c:&Ctx,eid:u32)->(i32,i32) {let x=c.minion(eid).unwrap();(x.atk,x.max_hp)}
fn me(id:&str,eid:u32)->Me {Me{side:0,eid,card:cid(id),golden:db().get(cid(id)).normal.is_some(),opt:0,pos:0,data:0}}
fn give(g:&mut Game,p:usize,id:&str) {g.with_recruit(p,|c|{c.give_card(0,cid(id));});}
fn play(g:&mut Game,p:usize,id:&str) {give(g,p,id);let hand=g.players[p].hand.len()-1;let pos=if db().get(cid(id)).kind==taverngym::cards::CardKind::Minion{g.players[p].board.len()}else{0};g.apply(p,Action::Play{hand,pos}).unwrap();}
fn cast_on(g:&mut Game,id:&str,eid:u32) {
    play(g,0,id);
    let Some(Pending::Target{options,..})=g.players[0].pending.last() else{panic!("missing target")};
    let i=options.iter().position(|x|*x==eid).unwrap();g.apply(0,Action::Choose(i)).unwrap();
}
fn played(side:usize,eid:u32,races:Races)->Event {Event::Played{side,eid,played:PlayInfo{source:eid,card:cid("BG23_000"),races,atk:1,tier:1,golden:false,battlecry:false,repeated:false}}}

#[test]
fn exact_six_identities_require_effects() {
    for id in ["BG31_035","BG31_035_G"] {let s=script(cid(id)).expect("Groundbreaker missing");assert!(s.on_event.is_some());assert_eq!(s.listens&ev::PLAYED,ev::PLAYED);}
    for id in ["BG31_925","BG31_925_G"] {assert!(script(cid(id)).and_then(|s|s.deathrattle).is_some(),"Cyclist missing {id}");}
    for id in ["BG35_921","BG35_921_G"] {assert!(script(cid(id)).is_some(),"Bruiser missing {id}");assert!(m(9,id).has(Kw::DIVINE_SHIELD));}
}

#[test]
fn groundbreaker_thresholds_zero_two_three_five_six_normal_and_gold() {
    for (id,gold) in [("BG31_035",1),("BG31_035_G",2)] {for n in [0,2,3,5,6] {
        let mut g=game();g.players[0].stats.spells_cast=n;g.players[0].stats.tavern_spells_cast=0;
        let b=m(101,id);let before=(b.atk,b.max_hp);let mut c=Ctx::new(&mut g,[vec![b],vec![]],[Some(0),Some(1)],false);
        c.emit(played(0,201,Races::NAGA));let k=gold*(1+n/3);assert_eq!(stats(&c,101),(before.0+k,before.1+k),"{id}, casts={n}");
    }}
}

#[test]
fn groundbreaker_after_phase_own_play_including_self_and_alive_naga_only() {
    let mut g=game();let mut c=Ctx::new(&mut g,[vec![m(101,"BG31_035")],vec![]],[Some(0),Some(1)],false);
    let before=stats(&c,101);
    c.emit(played(1,201,Races::NAGA));c.emit(played(0,201,Races::BEAST));c.emit(Event::Summoned{side:0,eid:201});assert_eq!(stats(&c,101),before);
    c.play_phase=1;c.emit(played(0,101,Races::NAGA));assert_eq!(stats(&c,101),before);
    c.play_phase=2;c.emit(played(0,101,Races::NAGA));c.emit(played(0,201,Races::ALL));c.emit(played(0,202,Races::NAGA.union(Races::BEAST)));
    assert_eq!(stats(&c,101),(before.0+3,before.1+3));
    c.boards[0].clear();c.emit(played(0,201,Races::NAGA));assert!(c.boards[0].is_empty());
}

#[test]
fn actual_public_plays_count_spellcraft_gem_and_tavern_for_groundbreaker() {
    for id in ["BG31_035","BG31_035_G"] {
        let mut g=game();g.players[0].board.push(m(101,id));g.players[0].board.push(body(102,Races::BEAST));
        // All three increment spells_cast, only the Tavern Coin increments tavern_spells_cast.
        cast_on(&mut g,"BG23_000t",102);cast_on(&mut g,"BG20_GEM",102);play(&mut g,0,"BG28_810");
        assert_eq!(g.players[0].stats.spells_cast,3);assert_eq!(g.players[0].stats.tavern_spells_cast,1);
        let before=(g.players[0].board[0].atk,g.players[0].board[0].max_hp);
        play(&mut g,0,"BG23_000");let x=&g.players[0].board[0];let k=if x.golden{4}else{2};assert_eq!((x.atk,x.max_hp),(before.0+k,before.1+k));
        // Playing the source itself is a Naga play and triggers it once.
        let mut g=game();play(&mut g,0,id);let x=&g.players[0].board[0];let d=db().get(cid(id));let k=if x.golden{2}else{1};assert_eq!((x.atk,x.max_hp),(d.atk+k,d.hp+k));
    }
}

#[test]
fn cyclist_thresholds_normal_gold_targets_live_naga_dual_all_not_enemy_shop() {
    for (id,gold) in [("BG31_925",1),("BG31_925_G",2)] {for n in [0,2,3,5,6,7] {
        let mut g=game();g.players[0].stats.spells_cast=n;g.players[0].stats.tavern_spells_cast=0;
        g.players[0].shop.push(ShopSlot::new(300,Item::Minion(body(300,Races::NAGA))));
        let mut dead=body(105,Races::NAGA);dead.hp=0;
        let mut c=Ctx::new(&mut g,[vec![body(101,Races::NAGA),body(102,Races::ALL),body(103,Races::NAGA.union(Races::BEAST)),body(104,Races::BEAST),dead],vec![body(201,Races::NAGA)]],[Some(0),Some(1)],true);
        let fx=script(cid(id)).and_then(|s|s.deathrattle).expect("actual Cyclist deathrattle");fx(&mut c,me(id,900));let k=gold*(1+n/3);
        for e in [101,102,103] {assert_eq!(stats(&c,e),(10+2*k,10+k),"{id} casts={n}");}
        for e in [104,105,201] {assert_eq!(stats(&c,e),(10,10));}
        let x=c.player_ref(0).unwrap().shop[0].item.as_minion().unwrap();assert_eq!((x.atk,x.max_hp),(10,10));
    }}
}

#[test]
fn cyclist_actual_death_resolution_and_combat_buff_expires() {
    for (id,gold) in [("BG31_925",1),("BG31_925_G",2)] {
        let mut g=game();g.players[0].stats.spells_cast=6;g.players[0].board=vec![m(100,id),body(101,Races::NAGA)];
        let boards=[g.players[0].board.clone(),vec![]];{
            let mut c=Ctx::new(&mut g,boards,[Some(0),Some(1)],true);c.destroy(100);c.resolve_deaths();
            assert!(c.minion(100).is_none());assert_eq!(stats(&c,101),(10+6*gold,10+3*gold));c.resolve_deaths();assert_eq!(stats(&c,101),(10+6*gold,10+3*gold));
        }
        let x=&g.players[0].board[1];assert_eq!((x.atk,x.max_hp),(10,10));
    }
}

#[test]
fn bruiser_reversible_bonus_preserves_buffs_damage_and_recomputes_all_zones() {
    for (id,gold) in [("BG35_921",1),("BG35_921_G",2)] {
        let mut g=game();g.players[0].board=vec![m(101,id)];give(&mut g,0,id);g.players[0].shop.push(ShopSlot::new(103,Item::Minion(m(103,id))));
        g.with_recruit(0,|c| {c.buff(101,5,7);c.bump_player_stat(0,|s|s.tavern_spells_cast=3);});
        let b=&g.players[0].board[0];assert_eq!((b.atk,b.max_hp),(2*gold+5+6*gold,gold+7+3*gold));
        for x in [g.players[0].hand[0].item.as_minion().unwrap(),g.players[0].shop[0].item.as_minion().unwrap()] {assert_eq!((x.atk,x.max_hp),(8*gold,4*gold));}
        g.players[0].board[0].hp-=1;
        for _ in 0..3 {g.with_recruit(0,|c|c.bump_player_stat(0,|_|{}));}
        let b=&g.players[0].board[0];assert_eq!((b.atk,b.max_hp,b.hp),(8*gold+5,4*gold+7,4*gold+6));
        g.with_recruit(0,|c|c.bump_player_stat(0,|s|s.tavern_spells_cast=0));
        let b=&g.players[0].board[0];assert_eq!((b.atk,b.max_hp,b.hp),(2*gold+5,gold+7,gold+6));
    }
}

#[test]
fn public_spell_categories_bruiser_only_tavern_and_owner_scoped() {
    for (id,gold) in [("BG35_921",1),("BG35_921_G",2)] {
        let mut g=game();g.players[0].board=vec![m(101,id),body(102,Races::BEAST)];g.players[1].board=vec![m(201,id)];
        cast_on(&mut g,"BG23_000t",102);cast_on(&mut g,"BG20_GEM",102);
        let x=&g.players[0].board[0];assert_eq!((x.atk,x.max_hp),(2*gold,gold));
        play(&mut g,0,"BG28_810");let x=&g.players[0].board[0];assert_eq!((x.atk,x.max_hp),(4*gold,2*gold));
        let x=&g.players[1].board[0];assert_eq!((x.atk,x.max_hp),(2*gold,gold));
        play(&mut g,1,"BG28_810");let x=&g.players[1].board[0];assert_eq!((x.atk,x.max_hp),(4*gold,2*gold));
    }
}

#[test]
fn exact_raw_copy_restore_and_rng_continuation_after_real_actions() {
    let mut g=game();g.players[0].board=vec![m(101,"BG31_035"),m(102,"BG35_921")];
    cast_on(&mut g,"BG23_000t",101);play(&mut g,0,"BG28_810");
    let raw=serde_json::to_string(&g).unwrap();let mut restored:Game=serde_json::from_str(&raw).unwrap();let mut copied=g.clone();
    restored.check_loaded().unwrap();assert_eq!(serde_json::to_string(&restored).unwrap(),raw);assert_eq!(serde_json::to_string(&copied).unwrap(),raw);
    for branch in [&mut g,&mut restored,&mut copied] {play(branch,0,"BG28_810");play(branch,0,"BG23_000");branch.apply(0,Action::Refresh).unwrap();}
    assert_eq!(serde_json::to_string(&g).unwrap(),serde_json::to_string(&restored).unwrap());assert_eq!(serde_json::to_string(&g).unwrap(),serde_json::to_string(&copied).unwrap());
    assert_eq!(serde_json::to_string(&g.rng).unwrap(),serde_json::to_string(&restored.rng).unwrap());
    assert!(g.players[0].board[0].atk>db().get(cid("BG31_035")).atk);assert_eq!(g.players[0].board[1].atk,6);
}

#[test]
fn bruiser_full_copy_transfer_rebinds_owner_and_fresh_creation_uses_current_counter() {
    for (id,gold) in [("BG35_921",1),("BG35_921_G",2)] {
        let mut g=game();g.players[0].stats.tavern_spells_cast=3;g.players[1].stats.tavern_spells_cast=1;
        let copied=g.with_recruit(0,|c| {let mut x=c.new_minion(0,cid(id));x.add_stats(5,7);assert_eq!((x.atk,x.max_hp),(8*gold+5,4*gold+7));c.full_copy(&x)});
        g.players[1].board.push(copied);
        for _ in 0..3 {g.with_recruit(1,|c|c.bump_player_stat(0,|_|{}));}
        let x=&g.players[1].board[0];assert_eq!((x.atk,x.max_hp),(4*gold+5,2*gold+7));
        g.with_recruit(1,|c|c.bump_player_stat(0,|s|s.tavern_spells_cast=2));let x=&g.players[1].board[0];assert_eq!((x.atk,x.max_hp),(6*gold+5,3*gold+7));
        assert_eq!(g.players[0].stats.tavern_spells_cast,3);
    }
}

#[test]
fn dynamic_numbers_match_frozen_text_and_each_players_all_spell_count() {
    let mut g=game();g.players[0].stats.spells_cast=6;g.players[1].stats.spells_cast=0;
    let c=Ctx::new(&mut g,[vec![],vec![]],[Some(0),Some(1)],false);
    for (id,gold,base_atk) in [("BG31_035",1,1),("BG31_035_G",2,1),("BG31_925",1,2),("BG31_925_G",2,2)] {
        let f=script(cid(id)).and_then(|s|s.shown).expect("dynamic numbers required");
        for (side,k) in [(0,3),(1,1)] {let sh=taverngym::script::Shown{side,card:cid(id),golden:gold==2,minion:None,data:0};assert_eq!(f(&c,&sh),vec![base_atk*gold*k,gold*k,3]);}
    }
}
