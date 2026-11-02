//! W3 frozen target37 contracts; controlled fixtures, real public actions, no roster claim.
use taverngym::{Game,RulesConfig};
use taverngym::actions::Action;
use taverngym::cards::{cid,db};
use taverngym::engine::Ctx;
use taverngym::script::{script,Me};
use taverngym::state::{Item,Minion};
use taverngym::types::Races;
fn raw(g:&Game)->String {serde_json::to_string(g).unwrap()}
fn game()->Game {
 let mut g=Game::new(541,RulesConfig{num_players:2,lesser_trinket_turn:0,greater_trinket_turn:0,..RulesConfig::default()});
 for p in 0..2 {g.apply(p,Action::Choose(0)).unwrap();}
 for p in &mut g.players {p.board.clear();p.hand.clear();p.powers.clear();p.effects.clear();p.trinkets.clear();p.rewards.clear();p.quests.clear();p.secrets.clear();p.pending.clear();p.gold=30;p.tier=6;p.skipping=false;}
 g
}
fn body(g:&mut Game,id:&str,a:i32,h:i32)->Minion {let mut m=Minion::new(g.alloc_eid(),cid(id));m.set_stats(a,h);m}
fn add(g:&mut Game,p:usize,id:&str,a:i32,h:i32)->u32 {let m=body(g,id,a,h);let e=m.eid;g.players[p].board.push(m);e}
fn stats(g:&Game,p:usize,i:usize)->(i32,i32){let m=&g.players[p].board[i];(m.atk,m.max_hp)}
#[test]fn w3_real_effect_hooks_and_extra_power_dependency_required(){
 for id in ["BG32_837","BG32_837_G"] {assert!(script(cid(id)).and_then(|s|s.end_of_turn).is_some(),"Fauna EOT hook missing");}
 for id in ["BG34_925","BG34_925_G"] {assert!(script(cid(id)).and_then(|s|s.rally).is_some(),"Rally hook missing");}
 for id in ["BG36_508","BG36_508_G"] {assert!(script(cid(id)).and_then(|s|s.activate).is_some(),"Activate hook missing");}
 assert!(script(cid("BG22_HERO_007p")).is_some());assert!(script(cid("BG22_HERO_007p2")).and_then(|s|s.hero_power).is_some());
}
#[test]fn fauna_public_end_turn_normal_and_golden_primary_two_one(){
 for (id,expected) in [("BG32_837",(14,12)),("BG32_837_G",(18,14))] {
  let mut g=game();add(&mut g,0,"BGS_004",10,10);add(&mut g,0,id,10,10);add(&mut g,0,"BGS_004",10,10);
  g.apply(0,Action::EndTurn).unwrap();assert_eq!(stats(&g,0,0),expected);assert_eq!(stats(&g,0,2),expected);assert_eq!(stats(&g,0,1),(10,10));
  assert_eq!(g.players[0].stats.cards_played,0);assert_eq!(g.players[0].stats.tavern_spells_cast,0);
 }
}
#[test]fn fauna_source_and_typeless_edges_are_noops(){
 let mut g=game();assert!(db().get(cid("BG35_883")).races.is_none());add(&mut g,0,"BG35_883",10,10);add(&mut g,0,"BG32_837",10,10);g.apply(0,Action::EndTurn).unwrap();assert_eq!(stats(&g,0,0),(10,10));
 let mut g=game();add(&mut g,0,"BGS_004",10,10);g.apply(0,Action::EndTurn).unwrap();assert_eq!(stats(&g,0,0),(10,10));
}
#[test]fn seafloor_actual_combat_rally_normal_gold_and_typeless(){
 for (id,n) in [("BG34_925",1),("BG34_925_G",2)] {
  let mut g=game();g.cfg.max_combat_attacks=1;assert!(db().get(cid("BG35_883")).races.is_none());add(&mut g,0,id,1,100);add(&mut g,0,"BG35_883",1,100);add(&mut g,1,"BGS_039",1,1000);
  g.apply(0,Action::EndTurn).unwrap();let prefix=raw(&g);let mut c:Game=serde_json::from_str(&prefix).unwrap();
  for x in [&mut g,&mut c] {x.apply(1,Action::EndTurn).unwrap();}
  assert_eq!(raw(&g),raw(&c));assert_eq!(g.players[0].hand.len(),n);
  assert!(g.players[0].hand.iter().all(|h|h.item.card()==cid("BG28_521t")));
  assert_eq!(g.players[0].stats.tavern_spells_cast,0);
 }
}
#[test]fn cagey_public_activate_count_pay_once_target_self_and_exact_restore(){
 for (id,expected) in [("BG36_508",(14,12)),("BG36_508_G",(18,14))] {
  let mut g=game();add(&mut g,0,id,10,10);assert!(g.spell_universe.contains(&cid("BG28_845")),"fixture cannot add a missing spell to its universe");
  g.spell_universe.retain(|c|*c==cid("BG28_845"));let before=raw(&g);let mut c:Game=serde_json::from_str(&before).unwrap();
  for x in [&mut g,&mut c] {x.apply(0,Action::Activate(0)).unwrap();}
  assert_eq!(raw(&g),raw(&c));assert_eq!(stats(&g,0,0),expected);assert_eq!(g.players[0].gold,29);
  assert_eq!(g.players[0].stats.cards_played,0);assert_eq!(g.players[0].stats.tavern_spells_cast,0);
  let saved=raw(&g);assert!(g.apply(0,Action::Activate(0)).is_err());assert_eq!(raw(&g),saved);
 }
}
#[test]fn cagey_empty_set_still_pays_activate_but_draws_no_rng(){let mut g=game();add(&mut g,0,"BG36_508",10,10);g.spell_universe.clear();let rng=serde_json::to_string(&g.rng).unwrap();g.apply(0,Action::Activate(0)).unwrap();assert_eq!(stats(&g,0,0),(10,10));assert_eq!(g.players[0].gold,29);assert_eq!(serde_json::to_string(&g.rng).unwrap(),rng);}
#[test]fn ambition_29_to_30_actual_spell_play_replaces_only_owned_slot(){
 let mut g=game();add(&mut g,0,"BGS_004",29,50);g.players[0].set_hero_power(0,cid("BG22_HERO_007p"));g.players[0].set_hero_power(1,cid("BG31_HERO_005p"));g.players[1].set_hero_power(0,cid("BG22_HERO_007p"));
 g.with_recruit(0,|_|{});assert_eq!(g.players[0].powers[0].card,cid("BG22_HERO_007p"));
 g.with_recruit(0,|c|{c.add_to_hand(0,Item::spell(cid("BG_TB_006")));});
 let e=g.players[0].board[0].eid;g.apply(0,Action::Play{hand:0,pos:0}).unwrap();
 let options=match g.players[0].pending.last().unwrap(){taverngym::state::Pending::Target{options,..}=>options,_=>panic!("real target menu missing")};let ix=options.iter().position(|x|*x==e).unwrap();g.apply(0,Action::Choose(ix)).unwrap();
 assert_eq!(g.players[0].powers[0].card,cid("BG22_HERO_007p2"));assert_eq!(g.players[0].powers[1].card,cid("BG31_HERO_005p"));assert_eq!(g.players[1].powers[0].card,cid("BG22_HERO_007p"));
}
#[test]fn temporary_combat_attack_cannot_unlock_ambition(){let mut g=game();g.players[0].set_hero_power(0,cid("BG22_HERO_007p"));let m=body(&mut g,"BGS_004",30,10);let mut c=Ctx::new(&mut g,[vec![m],vec![]],[Some(0),Some(1)],true);taverngym::content::check_total_attack(&mut c,0);assert_eq!(c.g.players[0].powers[0].card,cid("BG22_HERO_007p"));}

#[test]fn triggered_hooks_only_original_hero_pair_is_delegated(){
 for id in ["BG32_837","BG32_837_G"] {assert!(script(cid(id)).and_then(|s|s.end_of_turn).is_some());}
 for id in ["BG34_925","BG34_925_G"] {assert!(script(cid(id)).and_then(|s|s.rally).is_some());}
 for id in ["BG36_508","BG36_508_G"] {assert!(script(cid(id)).and_then(|s|s.activate).is_some());}
}
#[test]fn cagey_choose_one_sequence_serializes_each_mode_and_pays_only_once(){
 for (id,n,expected) in [("BG36_508",2,(14,14)),("BG36_508_G",4,(18,18))] {
  let mut g=game();add(&mut g,0,id,10,10);assert!(g.spell_universe.contains(&cid("BG31_880")));
  g.spell_universe.retain(|c|*c==cid("BG31_880"));g.apply(0,Action::Activate(0)).unwrap();assert_eq!(stats(&g,0,0),(10,10));
  let prefix=raw(&g);let mut copy:Game=serde_json::from_str(&prefix).unwrap();assert_eq!(raw(&copy),prefix);
  for i in 0..n {
   assert!(matches!(g.players[0].pending.last(),Some(taverngym::state::Pending::ChooseOne{..})));
   let before=raw(&g);assert!(g.apply(0,Action::Cancel).is_err());assert_eq!(raw(&g),before);
   for x in [&mut g,&mut copy] {x.apply(0,Action::Choose(i%2)).unwrap();}
   assert_eq!(raw(&g),raw(&copy));assert_eq!(g.players[0].gold,29);
  }
  assert!(g.players[0].pending.is_empty());assert_eq!(stats(&g,0,0),expected);assert_eq!(g.players[0].stats.cards_played,0);assert_eq!(g.players[0].stats.tavern_spells_cast,0);
 }
}
#[test]fn cagey_real_resolving_triggers_owned_lorewalker_without_hand_counters(){
 for (id,expected) in [("BG36_508",(22,20)),("BG36_508_G",(34,30))] {
  let mut g=game();add(&mut g,0,id,10,10);g.players[0].trinkets.push(cid("BG30_MagicItem_422"));assert!(g.spell_universe.contains(&cid("BG28_845")));g.spell_universe.retain(|c|*c==cid("BG28_845"));
  g.apply(0,Action::Activate(0)).unwrap();assert_eq!(stats(&g,0,0),expected);assert_eq!(g.players[0].stats.cards_played,0);assert_eq!(g.players[0].stats.spells_cast,0);
 }
}
#[test]fn seafloor_rightmost_or_dead_right_neighbor_no_generated_card(){
 for dead in [false,true] {let mut g=game();let eid=add(&mut g,0,"BG34_925",10,10);if dead {let e=add(&mut g,0,"BGS_004",10,10);g.players[0].board.iter_mut().find(|m|m.eid==e).unwrap().hp=0;}
  g.with_recruit(0,|c|{let fx=script(cid("BG34_925")).unwrap().rally.unwrap();fx(c,Me{side:0,eid,card:cid("BG34_925"),golden:false,opt:0,pos:0,data:0},0);});assert!(g.players[0].hand.is_empty());}
}
