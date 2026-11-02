//! Two current formal spells on a fixed D03 Rust baseline. Controlled construction, not natural acquisition.
use taverngym::{Game,RulesConfig};
use taverngym::actions::Action;
use taverngym::cards::{cid,db};
use taverngym::engine::Ctx;
use taverngym::script::script;
use taverngym::state::{Item,Minion,Pending,ShopSlot};

fn body(eid:u32,id:&str)->Minion {let mut m=Minion::new(eid,cid(id));m.set_stats(10,10);m}
fn game()->Game {
 let mut g=Game::new(541,RulesConfig{num_players:2,record_log:true,..RulesConfig::default()});
 for p in 0..2 {g.apply(p,Action::Choose(0)).unwrap();}
 for p in &mut g.players {p.pending.clear();p.hand.clear();p.board.clear();p.shop.clear();p.powers.clear();p.effects.clear();p.quests.clear();p.trinkets.clear();p.counters.clear();p.stats=Default::default();p.gold=10;p.tier=6;p.skipping=false;}
 g.next_eid=100;g
}
fn stats(c:&Ctx,e:u32)->(i32,i32) {let m=c.minion(e).unwrap();(m.atk,m.max_hp)}
fn raw(g:&Game)->String {serde_json::to_string(g).unwrap()}
fn give(g:&mut Game,id:&str) {g.with_recruit(0,|c|{c.give_card(0,cid(id));});}
fn resolve(g:&mut Game,eid:u32) {
 let options=match g.players[0].pending.last().unwrap() {Pending::Target{options,..}=>options,_=>panic!("not target pending")};
 let i=options.iter().position(|e|*e==eid).unwrap();g.apply(0,Action::Choose(i)).unwrap();
}

#[test]
fn callbacks_exist_and_queen_current_dynamic_text_is_two_three() {
 for id in ["BG32_815","BG35_922"] {assert!(script(cid(id)).and_then(|s|s.spell).is_some(),"missing native callback {id}");}
 assert_eq!(db().get(cid("BG35_922")).text,"Give your minions +2/+3. Give all your Naga another +2/+3.");
}

#[test]
fn shifting_distinct_buffs_extra_stats_and_stat_gain_events() {
 for (id,times) in [("BGS_115",2),("BG23_004",4),("BG25_039",4),("BG24_017",4)] {
  let mut g=game();g.players[0].stats.spell_atk=2;g.players[0].stats.spell_hp=3;
  let mut c=Ctx::new(&mut g,[vec![body(101,id),body(102,"TB_BaconShop_HERO_52_Buddy")],vec![body(103,"BGS_115")]],[Some(0),Some(1)],true);
  c.cast_spell(0,cid("BG32_815"),0,101,0);
  // Sinestra grants +1 Health once per independent Attack-gain event, distinguishing a collapsed buff.
  assert_eq!(stats(&c,101),(10+3*times,10+5*times),"{id}: each1/1+extra2/3 plus independent Sinestra event");
  assert_eq!(stats(&c,103),(10,10));
 }
}

#[test]
fn queen_two_three_all_then_naga_dual_all_with_sentinels() {
 let mut g=game();g.players[0].stats.spell_atk=1;g.players[0].stats.spell_hp=2;
 g.players[0].shop.push(ShopSlot::new(120,Item::Minion(body(120,"BG23_004"))));
 let mut dead=body(105,"BG23_004");dead.hp=0;
 let mut c=Ctx::new(&mut g,[vec![body(101,"BGS_115"),body(102,"BG23_004"),body(103,"BG25_039"),body(104,"BG24_017"),dead],vec![body(106,"BG23_004")]],[Some(0),Some(1)],false);
 // Invoke the component callback directly so the deliberately dead sentinel is still inspectable;
 // public cast/death-resolution and hand lifecycle are tested separately below.
 let me=taverngym::script::Me{side:0,eid:0,card:cid("BG35_922"),golden:false,opt:0,pos:0,data:0};
 script(me.card).unwrap().spell.unwrap()(&mut c,me,0);
 assert_eq!(stats(&c,101),(13,15));for e in [102,103,104] {assert_eq!(stats(&c,e),(16,20));}
 assert_eq!(stats(&c,105),(10,10));assert_eq!(stats(&c,106),(10,10));
 let m=c.player_ref(0).unwrap().shop[0].item.as_minion().unwrap();assert_eq!((m.atk,m.max_hp),(10,10));
}

#[test]
fn public_buy_target_cancel_invalid_choose_consumption_and_cost_once() {
 let mut g=game();g.players[0].board.push(body(101,"BG23_004"));
 g.players[1].board.push(body(102,"BG23_004"));
 g.players[0].shop.push(ShopSlot::new(103,Item::spell(cid("BG32_815"))));
 g.apply(0,Action::Buy(0)).unwrap();assert_eq!(g.players[0].gold,9);assert_eq!(g.players[0].hand.len(),1);
 g.apply(0,Action::Play{hand:0,pos:0}).unwrap();
 assert!(matches!(g.players[0].pending.last(),Some(Pending::Target{..})),"public cast must open target confirmation");
 assert_eq!(g.players[0].hand.len(),1);let pending=raw(&g);
 assert!(g.apply(0,Action::Choose(99)).is_err());assert_eq!(raw(&g),pending);
 g.apply(0,Action::Cancel).unwrap();assert!(g.players[0].pending.is_empty());assert_eq!(g.players[0].hand.len(),1);assert_eq!(g.players[0].gold,9);
 g.apply(0,Action::Play{hand:0,pos:0}).unwrap();resolve(&mut g,101);
 assert!(g.players[0].hand.is_empty());assert!(g.players[0].pending.is_empty());assert_eq!(g.players[0].gold,9);
 assert_eq!((g.players[0].board[0].atk,g.players[0].board[0].max_hp),(14,14));
 assert_eq!((g.players[1].board[0].atk,g.players[1].board[0].max_hp),(10,10));
 assert_eq!(g.players[0].stats.cards_played,1);
}

#[test]
fn public_queen_consumes_once_and_empty_board_resolves() {
 for populated in [false,true] {
  let mut g=game();if populated {g.players[0].board.push(body(101,"BG23_004"));}
  g.players[0].shop.push(ShopSlot::new(103,Item::spell(cid("BG35_922"))));
  g.apply(0,Action::Buy(0)).unwrap();assert_eq!(g.players[0].gold,8);
  g.apply(0,Action::Play{hand:0,pos:0}).unwrap();assert!(g.players[0].hand.is_empty());assert!(g.players[0].pending.is_empty());assert_eq!(g.players[0].gold,8);assert_eq!(g.players[0].stats.cards_played,1);
  if populated {let m=&g.players[0].board[0];assert_eq!((m.atk,m.max_hp),(14,16));}
 }
}

#[test]
fn shifting_no_candidates_rejected_without_consumption() {
 let mut g=game();give(&mut g,"BG32_815");g.players[0].shop.clear();let before=raw(&g);
 assert!(g.apply(0,Action::Play{hand:0,pos:0}).is_err());assert_eq!(raw(&g),before);
}

#[test]
fn public_target_prefix_copy_restore_raw_continuation_exact() {
 let mut g=game();g.players[0].board.push(body(101,"BG25_039"));give(&mut g,"BG32_815");
 let initial=raw(&g);let mut h:Game=serde_json::from_str(&initial).unwrap();let mut clone=g.clone();
 assert_eq!(raw(&h),initial);assert_eq!(raw(&clone),initial);
 for branch in [&mut g,&mut h,&mut clone] {branch.apply(0,Action::Play{hand:0,pos:0}).unwrap();}
 assert_eq!(raw(&g),raw(&h));assert_eq!(raw(&g),raw(&clone));
 assert!(matches!(g.players[0].pending.last(),Some(Pending::Target{..})));
 let open=raw(&g);let mut restored:Game=serde_json::from_str(&open).unwrap();
 for branch in [&mut g,&mut h,&mut clone,&mut restored] {resolve(branch,101);}
 assert_eq!(raw(&g),raw(&h));assert_eq!(raw(&g),raw(&clone));assert_eq!(raw(&g),raw(&restored));
 let m=&g.players[0].board[0];assert_eq!((m.atk,m.max_hp),(14,14));
}
