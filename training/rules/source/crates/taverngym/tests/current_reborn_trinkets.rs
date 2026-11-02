use taverngym::{Game,RulesConfig};
use taverngym::actions::Action;
use taverngym::cards::cid;
use taverngym::engine::Ctx;
use taverngym::state::Minion;
use taverngym::types::Kw;
const APPLE:&str="BG35_MagicItem_731";
const STICKER:&str="BG36_MagicItem_205";
fn game()->Game{let mut g=Game::new(21,RulesConfig{num_players:2,record_log:true,lesser_trinket_turn:0,greater_trinket_turn:0,..Default::default()});for p in 0..2{g.apply(p,Action::Choose(0)).unwrap();}for p in &mut g.players{p.pending.clear();p.board.clear();p.hand.clear();p.shop.clear();p.powers.clear();p.effects.clear();p.quests.clear();p.trinkets.clear();p.counters.clear();p.turn_data.clear();p.stats=Default::default();p.gold=30;p.tier=6;p.health=1000;p.armor=0;p.skipping=false;}g.next_eid=100;g.turn=7;g}
fn raw(g:&Game)->String{serde_json::to_string(g).unwrap()}
fn context(g:&mut Game)->Ctx<'_>{let boards=[g.players[0].board.clone(),g.players[1].board.clone()];Ctx::new(g,boards,[Some(0),Some(1)],true)}
fn body(e:u32,id:&str)->Minion{Minion::new(e,cid(id))}
#[test]fn apple_real_reborn_new_lives_regrant_only_first_three_successes(){
 let mut g=game();g.players[0].trinkets.push(cid(APPLE));g.players[0].board.push(body(10,"BG25_001"));let mut c=context(&mut g);let mut seen=vec![10];
 for i in 0..4{let old=c.boards[0][0].eid;c.destroy(old);c.resolve_deaths();assert_eq!(c.boards[0].len(),1);let m=&c.boards[0][0];assert!(!seen.contains(&m.eid));seen.push(m.eid);assert_eq!(m.has(Kw::REBORN),i<3,"each actual new body gets Reborn for first3 only");assert_eq!(c.turn_data(0,cid(APPLE)),(i+1).min(3));}
 assert_eq!(c.cstats[0].reborns,4);
}
#[test]fn apple_limit_is_shared_across_friendly_undead_bodies(){
 let mut g=game();g.players[0].trinkets.push(cid(APPLE));g.players[0].board=vec![body(10,"BG25_001"),body(11,"BG25_001")];let mut c=context(&mut g);for (i,pos) in [0usize,1,0,1].into_iter().enumerate(){let old=c.boards[0][pos].eid;c.destroy(old);c.resolve_deaths();assert_eq!(c.boards[0][pos].has(Kw::REBORN),i<3);assert_eq!(c.turn_data(0,cid(APPLE)),(i as i32+1).min(3));}assert_eq!(c.cstats[0].reborns,4);
}
#[test]fn apple_non_undead_reborn_does_not_spend_its_limit(){
 let mut g=game();g.players[0].trinkets.push(cid(APPLE));let mut m=body(10,"BGS_004");m.give(Kw::REBORN);g.players[0].board.push(m);let mut c=context(&mut g);c.destroy(10);c.resolve_deaths();assert_eq!(c.cstats[0].reborns,1);assert_eq!(c.turn_data(0,cid(APPLE)),0);assert!(!c.boards[0][0].has(Kw::REBORN));
}
#[test]fn sticker_actual_reborn_buffs_new_body_and_all_other_live_friends(){
 let mut g=game();g.players[0].trinkets.push(cid(STICKER));g.players[0].board=vec![body(10,"BG25_001"),body(11,"BGS_004")];let mut c=context(&mut g);c.destroy(10);c.resolve_deaths();let new=&c.boards[0][0];assert_ne!(new.eid,10);assert_eq!((new.atk,new.hp,new.max_hp),(4,3,3));let other=c.minion(11).unwrap();assert_eq!((other.atk,other.hp,other.max_hp),(3,5,5));assert_eq!(c.cstats[0].reborns,1);
}
#[test]fn opposite_owners_and_event_side_are_isolated(){
 let mut g=game();g.players[0].trinkets.push(cid(APPLE));g.players[1].trinkets.push(cid(STICKER));g.players[0].board.push(body(10,"BG25_001"));g.players[1].board.push(body(20,"BG25_001"));let mut c=context(&mut g);c.destroy(20);c.resolve_deaths();assert_eq!(c.turn_data(0,cid(APPLE)),0);assert_eq!((c.boards[1][0].atk,c.boards[1][0].max_hp),(4,3));c.destroy(10);c.resolve_deaths();assert!(c.boards[0][0].has(Kw::REBORN));assert_eq!((c.boards[0][0].atk,c.boards[0][0].max_hp),(2,1));assert_eq!((c.boards[1][0].atk,c.boards[1][0].max_hp),(4,3));assert_eq!(c.turn_data(0,cid(APPLE)),1);
}
#[test]fn deathrattle_fills_last_space_failed_reborn_emits_neither_trinket_effect(){
 let mut g=game();g.players[0].trinkets=vec![cid(APPLE),cid(STICKER)];let mut rat=body(10,"BG19_010");rat.give(Kw::REBORN);g.players[0].board.push(rat);for e in 11..17{g.players[0].board.push(body(e,"BGS_004"));}let mut c=context(&mut g);c.destroy(10);c.resolve_deaths();assert_eq!(c.boards[0].len(),7);assert_eq!(c.cstats[0].reborns,0);assert_eq!(c.turn_data(0,cid(APPLE)),0);assert_eq!(c.boards[0].iter().filter(|m|m.card==cid("BG19_010t")).count(),1);for m in c.boards[0].iter().filter(|m|m.card==cid("BGS_004")){assert_eq!((m.atk,m.max_hp),(1,3));}
}
fn battle_game()->Game{let mut g=game();g.players[0].board=vec![body(10,"BG25_001"),body(11,"BGS_004")];let mut enemy=body(20,"BGS_004");enemy.set_stats(100,10000);g.players[1].board.push(enemy);g}
#[test]fn apple_cap_is_per_turn_across_combats_and_real_turn_start_resets(){
 let mut g=battle_game();g.players[0].trinkets.push(cid(APPLE));let saved_board=g.players[0].board.clone();let out=g.simulate_combat(0,Some(1),None);assert!(!out.truncated);assert_eq!(out.stats[0].reborns,4);assert_eq!(g.players[0].board,saved_board);assert_eq!(g.players[0].turn_data.iter().find(|x|x.0==cid(APPLE)).unwrap().1,3);let out=g.simulate_combat(0,Some(1),None);assert!(!out.truncated);assert_eq!(out.stats[0].reborns,1);g.start_turn();assert!(!g.players[0].turn_data.iter().any(|x|x.0==cid(APPLE)));let out=g.simulate_combat(0,Some(1),None);assert!(!out.truncated);assert_eq!(out.stats[0].reborns,4);
}
#[test]fn both_trinkets_real_combat_three_regrants_four_buff_events_and_recruit_rollback_raw_restore(){
 let mut g=battle_game();g.players[0].trinkets=vec![cid(APPLE),cid(STICKER)];let before=raw(&g);let board=g.players[0].board.clone();let mut clone=g.clone();let mut restored:Game=serde_json::from_str(&before).unwrap();
 for b in [&mut g,&mut clone,&mut restored]{let out=b.simulate_combat(0,Some(1),None);assert!(!out.truncated);assert_eq!(out.stats[0].reborns,4);assert_eq!(b.players[0].board,board);assert!(b.last_frames.iter().any(|f|f.boards[0].iter().any(|m|m.eid==11 && m.atk==9 && m.max_hp==11)));assert_eq!(b.players[0].turn_data.iter().find(|x|x.0==cid(APPLE)).unwrap().1,3);}
 assert_eq!(raw(&g),raw(&clone));assert_eq!(raw(&g),raw(&restored));
}
#[test]fn midturn_limit_is_serialized_and_next_real_turn_resets_all_restored_branches(){
 let mut g=battle_game();g.players[0].trinkets.push(cid(APPLE));assert_eq!(g.simulate_combat(0,Some(1),None).stats[0].reborns,4);let prefix=raw(&g);let mut restored:Game=serde_json::from_str(&prefix).unwrap();for b in [&mut g,&mut restored]{let out=b.simulate_combat(0,Some(1),None);assert!(!out.truncated);assert_eq!(out.stats[0].reborns,1);}assert_eq!(raw(&g),raw(&restored));for b in [&mut g,&mut restored]{b.start_turn();let out=b.simulate_combat(0,Some(1),None);assert!(!out.truncated);assert_eq!(out.stats[0].reborns,4);}assert_eq!(raw(&g),raw(&restored));
}
#[test]fn reversing_the_two_owned_trinket_slots_keeps_each_scoped_effect_once(){
 for trinkets in [vec![cid(APPLE),cid(STICKER)],vec![cid(STICKER),cid(APPLE)]]{let mut g=game();g.players[0].trinkets=trinkets;g.players[0].board=vec![body(10,"BG25_001"),body(11,"BGS_004")];let mut c=context(&mut g);c.destroy(10);c.resolve_deaths();assert_eq!(c.cstats[0].reborns,1);assert!(c.boards[0][0].has(Kw::REBORN));assert_eq!((c.boards[0][0].atk,c.boards[0][0].max_hp),(4,3));assert_eq!((c.minion(11).unwrap().atk,c.minion(11).unwrap().max_hp),(3,5));assert_eq!(c.turn_data(0,cid(APPLE)),1);}
}
#[test]fn sticker_applies_after_non_undead_reborn_and_combat_stats_do_not_leak(){
 let mut g=battle_game();g.players[0].trinkets.push(cid(STICKER));let mut m=body(10,"BGS_004");m.give(Kw::REBORN);g.players[0].board[0]=m;let board=g.players[0].board.clone();let out=g.simulate_combat(0,Some(1),None);assert!(!out.truncated);assert_eq!(out.stats[0].reborns,1);assert_eq!(g.players[0].board,board);assert!(g.last_frames.iter().any(|f|f.boards[0].iter().any(|m|m.eid!=10 && m.eid!=11 && m.atk==3 && m.max_hp==5)));
}
