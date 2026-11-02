//! Focused final contract controls. Official dated stats and user semantic oracles are separate.
use taverngym::{Game, RulesConfig};
use taverngym::actions::Action;
use taverngym::cards::cid;
use taverngym::event::Event;
use taverngym::state::{Item, Minion, Pending, ShopSlot};
use taverngym::types::Races;
fn game() -> Game {
 let mut g=Game::new(17,RulesConfig{num_players:2,record_log:true,..Default::default()});
 for p in 0..2 {g.apply(p,Action::Choose(0)).unwrap();}
 for p in &mut g.players {
  p.pending.clear();p.hand.clear();p.board.clear();p.shop.clear();p.powers.clear();p.effects.clear();p.quests.clear();p.trinkets.clear();p.counters.clear();p.stats=Default::default();p.gold=30;p.tier=6;p.skipping=false;
 }
 g.next_eid=200;g
}
fn body(e:u32,id:&str)->Minion {Minion::new(e,cid(id))}
fn raw(g:&Game)->String {serde_json::to_string(g).unwrap()}
fn target(g:&mut Game,e:u32) {
 let opts=match g.players[0].pending.last().unwrap(){Pending::Target{options,..}=>options,_=>panic!()};
 let i=opts.iter().position(|x|*x==e).unwrap();g.apply(0,Action::Choose(i)).unwrap();
}
fn give(g:&mut Game,id:&str){g.with_recruit(0,|c|{c.give_card(0,cid(id));});}
fn eonar(g:&mut Game,e:u32) {give(g,"BG35_912");let h=g.players[0].hand.len()-1;g.apply(0,Action::Play{hand:h,pos:0}).unwrap();target(g,e);}
#[test]
fn gunpowder_public_spend_overshoot_discards_surplus_normal_gold() {
 for (id,n,a,h) in [("BG26_810",1,2,5),("BG26_810_G",2,4,10)] {
  let mut g=game();let mut m=body(101,id);m.counter=4;g.players[0].board.push(m);
  g.players[1].board.push(body(103,id));
  g.players[0].shop.push(ShopSlot::new(102,Item::Minion(body(102,"BGS_115"))));
  let before=raw(&g);let mut clone=g.clone();let mut restored:Game=serde_json::from_str(&before).unwrap();
  for b in [&mut g,&mut clone,&mut restored] {
   b.apply(0,Action::Buy(0)).unwrap();let m=&b.players[0].board[0];
   assert_eq!((m.counter,m.atk,m.max_hp),(0,a+3*n,h+n));
   assert_eq!(b.players[1].board[0].counter,0);
  }
  assert_eq!(raw(&g),raw(&clone));assert_eq!(raw(&g),raw(&restored));
 }
}
#[test]
fn gunpowder_large_single_event_once_then_next_event_restarts() {
 for (id,n,a,h) in [("BG26_810",1,2,5),("BG26_810_G",2,4,10)] {
  let mut g=game();g.players[0].board.push(body(101,id));
  g.with_recruit(0,|c|c.emit(Event::GoldSpent{side:0,amount:12}));
  let m=&g.players[0].board[0];assert_eq!((m.counter,m.atk,m.max_hp),(0,a+3*n,h+n));
  g.with_recruit(0,|c|c.emit(Event::GoldSpent{side:0,amount:4}));
  assert_eq!(g.players[0].board[0].counter,4);
  g.with_recruit(0,|c|c.emit(Event::GoldSpent{side:0,amount:1}));
  let m=&g.players[0].board[0];assert_eq!((m.counter,m.atk,m.max_hp),(0,a+6*n,h+2*n));
 }
}
#[test]
fn gunpowder_buy_third_triggers_old_bodies_before_natural_triple_resets_progress() {
 let mut g=game();for e in [101,102] {let mut m=body(e,"BG26_810");m.counter=3;g.players[0].board.push(m);}
 g.players[0].shop.push(ShopSlot::new(103,Item::Minion(body(103,"BG26_810"))));
 let before=raw(&g);let mut clone=g.clone();let mut restored:Game=serde_json::from_str(&before).unwrap();
 for b in [&mut g,&mut clone,&mut restored] {
  b.apply(0,Action::Buy(0)).unwrap();assert!(b.players[0].board.is_empty());
  let m=b.players[0].hand.iter().find_map(|h|h.item.as_minion()).unwrap();
  assert_eq!(m.card,cid("BG26_810_G"));assert_eq!((m.atk,m.max_hp,m.counter),(16,14,0));
 }
 assert_eq!(raw(&g),raw(&clone));assert_eq!(raw(&g),raw(&restored));
}
#[test]
fn eonar_dual_picks_one_belonging_type_with_exact_one_rng_draw() {
 for seed in 0..16 {
  let mut g=game();g.rng=taverngym::rng::Rng::new(seed);g.players[0].board.push(body(101,"BG25_039"));
  let mut rng=g.rng.clone();let candidates=[Races::QUILBOAR,Races::NAGA];let expected=rng.pick(&candidates).unwrap().0;
  eonar(&mut g,101);assert_eq!(g.players[0].stats.tavern_race,vec![(expected,3,3)]);assert_eq!(g.rng,rng);
 }
}
#[test]
fn eonar_single_no_draw_all_exactly_one_current_lobby_draw() {
 let mut single=game();single.players[0].board.push(body(101,"BG23_004"));let rng=single.rng.clone();
 eonar(&mut single,101);assert_eq!(single.rng,rng);assert_eq!(single.players[0].stats.tavern_race,vec![(Races::NAGA.0,3,3)]);
 let mut all=game();all.players[0].board.push(body(101,"BG24_017"));let mut rng=all.rng.clone();
 let candidates:Vec<_>=all.lobby_races.iter().collect();assert!(!candidates.is_empty());let expected=rng.pick(&candidates).unwrap().0;
 eonar(&mut all,101);assert_eq!(all.rng,rng);assert_eq!(all.players[0].stats.tavern_race,vec![(expected,3,3)]);
}
#[test]
fn eonar_public_target_domain_cancel_and_repeated_persistent_tavern_aura() {
 let mut g=game();g.players[0].board.extend([body(101,"BG23_004"),body(102,"AT_121")]);
 g.players[1].board.push(body(103,"BG23_004"));
 g.players[0].shop.extend([ShopSlot::new(104,Item::Minion(body(104,"BG23_004"))),ShopSlot::new(105,Item::Minion(body(105,"AT_121")))]);
 g.players[1].shop.push(ShopSlot::new(106,Item::Minion(body(106,"BG23_004"))));
 give(&mut g,"BG35_912");let initial=raw(&g);g.apply(0,Action::Play{hand:0,pos:0}).unwrap();
 let opts=match g.players[0].pending.last().unwrap(){Pending::Target{options,..}=>options.clone(),_=>panic!()};assert_eq!(opts,vec![101,104]);
 let pending=raw(&g);assert!(g.apply(0,Action::Choose(99)).is_err());assert_eq!(raw(&g),pending);
 g.apply(0,Action::Cancel).unwrap();let mut expected:Game=serde_json::from_str(&initial).unwrap();expected.players[0].actions_this_turn+=2;assert_eq!(raw(&g),raw(&expected));
 g.apply(0,Action::Play{hand:0,pos:0}).unwrap();let prefix=raw(&g);let mut clone=g.clone();let mut restored:Game=serde_json::from_str(&prefix).unwrap();
 for b in [&mut g,&mut clone,&mut restored] {target(b,104);}
 assert_eq!(raw(&g),raw(&clone));assert_eq!(raw(&g),raw(&restored));
 for b in [&mut g,&mut clone,&mut restored] {
  eonar(b,101);let m=b.players[0].shop[0].item.as_minion().unwrap();let base=taverngym::cards::db().get(cid("BG23_004"));assert_eq!((m.atk,m.max_hp),(base.atk+6,base.hp+6));
  let base=taverngym::cards::db().get(cid("BG23_004"));assert_eq!((b.players[0].board[0].atk,b.players[0].board[0].max_hp),(base.atk,base.hp));
  assert_eq!(b.players[1].shop[0].item.as_minion().unwrap().atk,2);
  b.apply(0,Action::Buy(0)).unwrap();let m=b.players[0].hand[0].item.as_minion().unwrap();let base=taverngym::cards::db().get(cid("BG23_004"));assert_eq!((m.atk,m.max_hp),(base.atk+6,base.hp+6));
  b.with_recruit(0,|c| {let mut fresh=body(150,"BG23_004");c.apply_tavern_buffs(0,&mut fresh);let base=taverngym::cards::db().get(fresh.card);assert_eq!((fresh.atk,fresh.max_hp),(base.atk+6,base.hp+6));});b.apply(0,Action::Refresh).unwrap();assert_eq!(b.players[0].stats.tavern_race,vec![(Races::NAGA.0,3,3),(Races::NAGA.0,3,3)]);
 }
 assert_eq!(raw(&g),raw(&clone));assert_eq!(raw(&g),raw(&restored));
}
fn expected_chosen_type(g:&mut Game,r:Races)->Races {
 let types:Vec<_>=if r==Races::ALL {g.lobby_races.iter().collect()}else{r.iter().collect()};
 if types.len()>1 {*g.rng.pick(&types).unwrap()}else{types.first().copied().unwrap_or(r)}
}
#[test]
fn same_root_staff_dual_single_all_exact_type_then_refresh_control() {
 use taverngym::script::{script,Me};
 for id in ["BG25_039","BG23_004","BG24_017"] {
  for seed in 0..8 {
   let mut g=game();g.rng=taverngym::rng::Rng::new(seed);g.players[0].board.push(body(101,id));let mut expected=g.clone();
   let race=expected.players[0].board[0].races;let chosen=expected_chosen_type(&mut expected,race);
   let me=Me{side:0,eid:0,card:cid("EBG_Spell_038"),golden:false,opt:0,pos:0,data:0};
   g.with_recruit(0,|c|script(me.card).unwrap().spell.unwrap()(c,me,101));
   expected.with_recruit(0,|c|c.refresh_shop_with(0,chosen,false));
   assert_eq!(raw(&g),raw(&expected),"{id} seed{seed}: exact source tribe selection and shop/RNG state");
  }
 }
}
#[test]
fn same_root_affinity_dual_single_all_each_due_trigger_picks_again_control() {
 use taverngym::script::{script,Me};
 for id in ["BG25_039","BG23_004","BG24_017"] {
  for seed in 0..8 {
   let mut g=game();g.rng=taverngym::rng::Rng::new(seed);let mut host=body(101,id);host.cycle=1;host.cycle_turn=0;g.players[0].board.push(host);let mut expected=g.clone();
   let me=Me{side:0,eid:101,card:cid("BG36_MidGameEffect_000t82"),golden:false,opt:0,pos:0,data:0};
   for _ in 0..2 {
    g.with_recruit(0,|c|script(me.card).unwrap().end_of_turn.unwrap()(c,me));
    let race=expected.players[0].board[0].races;let chosen=expected_chosen_type(&mut expected,race);
    expected.with_recruit(0,|c|{assert!(c.minion_turn_cycle(101,2));let tier=c.tier(0);if let Some(card)=c.random_minion(|d|d.tier<=tier && d.races.intersects(chosen)){c.give_card(0,card);}});
    assert_eq!(raw(&g),raw(&expected),"{id} seed{seed}: exact chosen tribe, repeated cycle, generated card and RNG");
   }
  }
 }
}
