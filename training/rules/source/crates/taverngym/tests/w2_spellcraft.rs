use taverngym::{Game,RulesConfig};
use taverngym::actions::Action;
use taverngym::cards::{cid,db};
use taverngym::script::script;
#[test]
fn w2_all_eight_generated_spells_have_effects() {
 for id in ["BG27_514","BG27_514_G","BG31_920","BG31_920_G","BG32_835","BG32_835_G","BG33_319","BG33_319_G"] {
  let d=db().get(cid(id)); let spell=d.spellcraft.unwrap();
  assert!(script(spell).and_then(|s|s.spell).is_some(),"missing effect for {id} -> {:?}",spell);
 }
}

use taverngym::state::{Minion,Item,Pending,ShopSlot};
use taverngym::types::Races;
fn game()->Game {
 let mut g=Game::new(543,RulesConfig{num_players:2,record_log:true,..RulesConfig::default()});
 for p in 0..2 {g.apply(p,Action::Choose(0)).unwrap();}
 for p in &mut g.players {p.pending.clear();p.hand.clear();p.board.clear();p.shop.clear();p.powers.clear();p.effects.clear();p.quests.clear();p.trinkets.clear();p.counters.clear();p.stats=Default::default();p.gold=10;p.tier=6;p.skipping=false;}
 g.next_eid=100;g.cfg.triple_copies=99;g
}
fn raw(g:&Game)->String {serde_json::to_string(g).unwrap()}
fn play(g:&mut Game) {let hand=g.players[0].hand.len()-1;let pos=g.players[0].board.len();g.apply(0,Action::Play{hand,pos}).unwrap();}
fn source(g:&mut Game,id:&str) {
 give(g,id);play(g);
 // A directly created Golden body also grants its ordinary Triple Reward.
 // Resolve that independent setup effect before exercising its Spellcraft.
 let reward=cid("TB_BaconShop_Triples_01");
 assert_eq!(g.players[0].hand.iter().filter(|h|h.item.card()==reward).count(),if id.ends_with("_G"){1}else{0});
 g.players[0].hand.retain(|h|h.item.card()!=reward);
}
fn give(g:&mut Game,id:&str) {g.with_recruit(0,|c|{c.give_card(0,cid(id));});}
#[test]
fn generation_is_exact_token_temporary_source_linked_and_full_hand_loses_spell() {
 for id in ["BG27_514","BG27_514_G","BG31_920","BG31_920_G","BG32_835","BG32_835_G","BG33_319","BG33_319_G"] {
  let mut g=game();source(&mut g,id);
  let m=&g.players[0].board[0];let h=&g.players[0].hand[0];
  assert_eq!(h.item.card(),db().get(cid(id)).spellcraft.unwrap());assert!(h.temporary);assert_eq!(h.src,m.eid);
  let eid=m.eid;g.players[0].hand.clear();
  for _ in 0..g.cfg.hand_size {give(&mut g,"BGS_200t");}
  let before=raw(&g);g.with_recruit(0,|c|c.give_spellcraft(0,eid));assert_eq!(raw(&g),before);
 }
}
#[test]
fn meditation_stacks_persists_after_source_sale_and_only_buffs_tavern_spells() {
 let mut g=game();give(&mut g,"BG32_835");play(&mut g);play(&mut g);
 give(&mut g,"BG32_835_Gt");play(&mut g);
 assert_eq!((g.players[0].stats.spell_atk,g.players[0].stats.spell_hp),(3,3));
 g.apply(0,Action::Sell(0)).unwrap();
 g.players[0].board.push(Minion::new(110,cid("BG23_000")));
 let (a,h)=(g.players[0].board[0].atk,g.players[0].board[0].max_hp);
 g.with_recruit(0,|c|c.cast_spell(0,cid("BG28_168"),0,110,0));
 assert_eq!((g.players[0].board[0].atk,g.players[0].board[0].max_hp),(a+4,h+4));
 g.with_recruit(0,|c|c.cast_spell(0,cid("BG23_000t"),0,110,0));
 assert_eq!((g.players[0].board[0].atk,g.players[0].board[0].max_hp),(a+6,h+4));
}
#[test]
fn siren_targets_exclude_both_zarjira_forms_cancel_and_invalid_choices_preserve_raw_rng() {
 for id in ["BG27_514","BG27_514_G"] {
  let mut g=game();source(&mut g,id);
  for (eid,id) in [(201,"BG27_514"),(202,"BG27_514_G"),(203,"BG23_000")] {
   let mut m=Minion::new(eid,cid(id));m.set_stats(13,17);
   g.players[0].shop.push(ShopSlot::new(eid,Item::Minion(m)));
  }
  let mut expected_cancel=g.clone();expected_cancel.players[0].actions_this_turn+=2;let before=raw(&expected_cancel);let hand=0;g.apply(0,Action::Play{hand,pos:0}).unwrap();
  let Some(Pending::Target{options,..})=g.players[0].pending.last() else {panic!("target missing")};
  assert_eq!(options,&vec![203]);
  let pending=raw(&g);assert!(g.apply(0,Action::Choose(99)).is_err());assert_eq!(raw(&g),pending);
  g.apply(0,Action::Cancel).unwrap();assert_eq!(raw(&g),before);
  g.apply(0,Action::Play{hand:0,pos:0}).unwrap();g.apply(0,Action::Choose(0)).unwrap();
  let n=if id.ends_with("_G") {2}else{1};assert_eq!(g.players[0].hand.len(),n);
  for h in &g.players[0].hand {let m=h.item.as_minion().unwrap();assert_eq!((m.atk,m.max_hp),(13,17));assert_ne!(m.eid,203);}
  assert_eq!(g.players[0].gold,10);
 }
}
#[test]
fn strategist_end_growth_live_source_sold_source_fallback_and_seeded_raw_equality() {
 for id in ["BG31_920","BG31_920_G"] {
  let mut g=game();source(&mut g,id);let eid=g.players[0].board[0].eid;
  assert_eq!(g.players[0].board[0].counter,1);
  g.with_recruit(0,|c|c.run_minion_hook(0,eid,|s|s.end_of_turn,1,"end"));
  assert_eq!(g.players[0].board[0].counter,2);
  // The fixed current roster controls candidates. This fixture gives a named tier-2 Naga.
  g.universe=vec![cid("BG23_002")];g.pool.put(cid("BG23_002"),4);
  let mut clone=g.clone();play(&mut g);play(&mut clone);assert_eq!(raw(&g),raw(&clone));
  assert_eq!(g.players[0].hand.len(),if id.ends_with("_G") {2}else{1});
  for h in &g.players[0].hand {assert_eq!(db().get(h.item.card()).tier,2);assert!(h.item.as_minion().unwrap().is(Races::NAGA));}
  g.players[0].hand.clear();g.with_recruit(0,|c|c.give_spellcraft(0,eid));
  g.apply(0,Action::Sell(0)).unwrap();g.universe=vec![cid("BG23_000")];g.pool.put(cid("BG23_000"),4);play(&mut g);
  for h in &g.players[0].hand {assert_eq!(db().get(h.item.card()).tier,1);}
 }
}
#[test]
fn rime_random_stat_spell_generation_normal_gold_seeded_and_empty_roster() {
 for (id,n) in [("BG33_319",1),("BG33_319_G",2)] {
  let mut g=game();source(&mut g,id);
  g.spell_universe=vec![cid("BG28_168"),cid("BG28_169"),cid("BGS_200t")];
  let mut clone=g.clone();play(&mut g);play(&mut clone);assert_eq!(raw(&g),raw(&clone));
  assert_eq!(g.players[0].hand.len(),n);
  for h in &g.players[0].hand {assert!([cid("BG28_168"),cid("BG28_169")].contains(&h.item.card()));assert!(!h.temporary);}
  g.players[0].hand.clear();g.spell_universe.clear();give(&mut g,if n==1 {"BG33_319t"}else{"BG33_319_Gt"});play(&mut g);assert!(g.players[0].hand.is_empty());
 }
}



#[test]
fn only_zarjira_in_shop_refuses_play_with_full_raw_equality() {
 let mut g=game();source(&mut g,"BG27_514");
 g.players[0].shop.push(ShopSlot::new(201,Item::Minion(Minion::new(201,cid("BG27_514_G")))));
 let before=raw(&g);assert!(g.apply(0,Action::Play{hand:0,pos:0}).is_err());assert_eq!(raw(&g),before);
}
#[test]
fn strategist_exhausted_pool_does_not_create_extra_copy_or_consume_rng() {
 let mut g=game();source(&mut g,"BG31_920_G");g.universe=vec![cid("BG23_000")];
 while g.pool.take(cid("BG23_000")) {}
 let rng=serde_json::to_string(&g.rng).unwrap();play(&mut g);
 assert!(g.players[0].hand.is_empty());assert_eq!(serde_json::to_string(&g.rng).unwrap(),rng);
}
#[test]
fn strategist_growth_caps_to_roster_and_stops_after_source_sale() {
 let mut g=game();source(&mut g,"BG31_920");let eid=g.players[0].board[0].eid;
 g.universe=vec![cid("BG23_002")];
 g.with_recruit(0,|c|c.run_minion_hook(0,eid,|s|s.end_of_turn,8,"end"));
 assert_eq!(g.players[0].board[0].counter,2);
 g.apply(0,Action::Sell(0)).unwrap();let before=raw(&g);
 g.with_recruit(0,|c|c.run_minion_hook(0,eid,|s|s.end_of_turn,1,"end"));assert_eq!(raw(&g),before);
}

