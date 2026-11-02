use taverngym::{Game,RulesConfig};
use taverngym::actions::Action;
use taverngym::cards::{cid,db};
use taverngym::state::{Minion,Pending,ShopSlot,Item};
use taverngym::script::script;
const ALTAR:&str="BG32_MagicItem_844";const PORTRAIT:&str="BG30_MagicItem_987";const CAPE:&str="BG32_MagicItem_286";
fn game()->Game {
 let mut g=Game::new(719,RulesConfig{num_players:2,record_log:true,lesser_trinket_turn:0,greater_trinket_turn:0,..Default::default()});
 for p in 0..2 {g.apply(p,Action::Choose(0)).unwrap();}
 for p in &mut g.players {p.pending.clear();p.hand.clear();p.board.clear();p.shop.clear();p.powers.clear();p.effects.clear();p.quests.clear();p.trinkets.clear();p.counters.clear();p.stats=Default::default();p.gold=30;p.tier=6;p.skipping=false;}
 g.next_eid=200;g
}
fn body(e:u32,id:&str)->Minion {let mut m=Minion::new(e,cid(id));m.set_stats(10,10);m}
fn raw(g:&Game)->String {serde_json::to_string(g).unwrap()}
fn give(g:&mut Game,id:&str){g.with_recruit(0,|c|{c.give_card(0,cid(id));});}
fn offer(g:&mut Game,id:&str,free:bool){g.players[0].pending.push(Pending::Trinket{options:vec![cid(id)],free,replace:None});}
fn acquire(g:&mut Game,id:&str){offer(g,id,true);g.apply(0,Action::Choose(0)).unwrap();}
fn target(g:&mut Game,e:u32){let opts=match g.players[0].pending.last().unwrap(){Pending::Target{options,..}=>options,_=>panic!()};let i=opts.iter().position(|x|*x==e).unwrap();g.apply(0,Action::Choose(i)).unwrap();}
fn narrow(g:&mut Game,id:&str){let card=cid(id);assert!(g.spell_universe.contains(&card),"must only narrow existing source candidates: {id}");g.spell_universe=vec![card];}
#[test]fn exact_callbacks_exist(){for id in [ALTAR,PORTRAIT,CAPE]{assert!(script(cid(id)).and_then(|s|s.on_attach).is_some(),"{id}");}for id in [PORTRAIT,CAPE]{assert!(script(cid(id)).and_then(|s|s.start_of_turn).is_some(),"{id}");}}
#[test]fn altar_public_paid_choose_actual_removals_no_sold_death_or_foreign_effects(){
 for count in [0,2,7] {
  let mut g=game();for i in 0..count {let ids=["BGS_115","BG19_010","BG26_810","BG23_004","BG23_000","BG24_017","AT_121"];let id=ids[i as usize];g.with_recruit(0,|c|{let mut m=c.new_minion(0,cid(id));c.take_pool_copy(&mut m);c.boards[0].push(m);});}
  g.players[1].board.push(body(101,"BG26_810"));give(&mut g,"BG26_810");g.players[0].shop.push(ShopSlot::new(102,Item::Minion(body(102,"BGS_115"))));
  let foreign=g.players[1].clone();let hand=g.players[0].hand.clone();let shop=g.players[0].shop.clone();
  let returns:Vec<_>=g.players[0].board.iter().map(|m|(m.card,m.pool_copies)).collect();let original_pool=g.pool.clone();
  assert_eq!(g.players[0].board.len(),count as usize);let price=g.trinket_price(0,cid(ALTAR));offer(&mut g,ALTAR,false);let prefix=raw(&g);let mut clone=g.clone();let mut restored:Game=serde_json::from_str(&prefix).unwrap();
  for b in [&mut g,&mut clone,&mut restored] {
   b.apply(0,Action::Choose(0)).unwrap();assert!(b.players[0].board.is_empty());assert_eq!(b.players[0].gold,30-price+3*count);
   assert_eq!(serde_json::to_string(&b.players[0].hand).unwrap(),serde_json::to_string(&hand).unwrap());assert_eq!(serde_json::to_string(&b.players[0].shop).unwrap(),serde_json::to_string(&shop).unwrap());assert_eq!(serde_json::to_string(&b.players[1]).unwrap(),serde_json::to_string(&foreign).unwrap());
   for card in [cid("BGS_115"),cid("BG19_010")] {let n:u8=returns.iter().filter(|(c,_)|*c==card).map(|(_,n)|*n).sum();assert_eq!(b.pool.get(card),original_pool.get(card)+n as u16);}
  }
  assert_eq!(raw(&g),raw(&clone));assert_eq!(raw(&g),raw(&restored));
 }
}
#[test]fn portrait_public_acquire_turn_start_and_full_hand_fifo(){
 let mut g=game();acquire(&mut g,PORTRAIT);assert_eq!(g.players[0].hand.len(),1);assert_eq!(g.players[0].hand[0].item.card(),cid("BG26_814"));g.start_turn();assert_eq!(g.players[0].hand.len(),2);
 let mut full=game();for _ in 0..full.cfg.hand_size {give(&mut full,"BG28_810");}acquire(&mut full,PORTRAIT);assert_eq!(full.players[0].hand_queue.len(),1);let promised=full.players[0].hand_queue_marks[0].hid;full.start_turn();assert_eq!(full.players[0].hand_queue.len(),2);
 let prefix=raw(&full);let mut twin=full.clone();let mut restored:Game=serde_json::from_str(&prefix).unwrap();for b in [&mut full,&mut twin,&mut restored]{b.apply(0,Action::Play{hand:0,pos:0}).unwrap();assert_eq!(b.players[0].hand.len(),10);assert_eq!(b.players[0].hand_queue.len(),1);assert!(b.players[0].hand.iter().any(|h|h.hid==promised && h.item.card()==cid("BG26_814")));}assert_eq!(raw(&full),raw(&twin));assert_eq!(raw(&full),raw(&restored));
}
#[test]fn balladist_normal_gold_real_spend_additive_health_and_portrait_only_attack(){
 for (id,n) in [("BG26_814",1),("BG26_814_G",2)] {for owned in [false,true] {
  let mut g=game();if owned {acquire(&mut g,PORTRAIT);g.players[0].hand.clear();}
  g.players[0].board.push(body(101,"BG26_810"));g.players[1].board.push(body(102,"BG26_810"));g.players[0].shop.push(ShopSlot::new(103,Item::Minion(body(103,"BGS_115"))));g.apply(0,Action::Buy(0)).unwrap();assert_eq!(g.players[0].stats.gold_spent_turn,3);
  give(&mut g,id);let h=g.players[0].hand.len()-1;g.apply(0,Action::Play{hand:h,pos:1}).unwrap();let prefix=raw(&g);let mut clone=g.clone();let mut restored:Game=serde_json::from_str(&prefix).unwrap();
  for b in [&mut g,&mut clone,&mut restored] {target(b,101);let m=&b.players[0].board[0];assert_eq!((m.atk,m.max_hp),(10+if owned {5*n}else{0},10+5*n));assert_eq!(b.players[1].board[0].atk,10);}
  assert_eq!(raw(&g),raw(&clone));assert_eq!(raw(&g),raw(&restored));
 }}
}
#[test]fn balladist_zero_spend_neighbor_target_and_unrelated_gem_not_modified(){
 for id in ["BG26_814","BG26_814_G"] {
  let mut g=game();acquire(&mut g,PORTRAIT);g.players[0].hand.clear();g.players[0].board.push(body(101,"BG26_810"));give(&mut g,id);g.apply(0,Action::Play{hand:0,pos:1}).unwrap();
  let source=g.players[0].board[1].eid;let opts=match g.players[0].pending.last().unwrap(){Pending::Target{options,..}=>options,_=>panic!()};assert!(!opts.contains(&source),"preserve existing played Battlecry no-self targeting contract");target(&mut g,101);
  let n=if id.ends_with("_G"){2}else{1};assert_eq!((g.players[0].board[0].atk,g.players[0].board[0].max_hp),(10+2*n,10+2*n));let before=(g.players[0].board[0].atk,g.players[0].board[0].max_hp);g.with_recruit(0,|c|c.you_cast(0,cid("BG20_GEM"),0,101,0));assert_eq!((g.players[0].board[0].atk,g.players[0].board[0].max_hp),(before.0+1,before.1+1));
 }
}#[test]fn cape_counts_union_dual_all_each_one_and_casts_even_with_full_hand(){
 for (ids,count) in [(vec![],0),(vec!["BG23_004","BG23_004"],1),(vec!["BG25_039"],2),(vec!["BG24_017"],1),(vec!["BG24_017","BG24_017"],2),(vec!["BG25_039","BG24_017","BG23_004"],3),(vec!["AT_121"],0)] {
  let mut g=game();for (i,id) in ids.iter().enumerate(){g.players[0].board.push(body(101+i as u32,id));}for _ in 0..g.cfg.hand_size {give(&mut g,"BG28_810");}narrow(&mut g,"BG28_810");offer(&mut g,CAPE,true);let prefix=raw(&g);let mut clone=g.clone();let mut restored:Game=serde_json::from_str(&prefix).unwrap();
  for b in [&mut g,&mut clone,&mut restored] {b.apply(0,Action::Choose(0)).unwrap();assert_eq!(b.players[0].gold,30+count);assert_eq!(b.players[0].stats.spells_cast,count);assert_eq!(b.players[0].hand.len(),10);assert!(b.players[0].hand_queue.is_empty());}
  assert_eq!(raw(&g),raw(&clone));assert_eq!(raw(&g),raw(&restored));
 }
}
#[test]fn cape_turn_start_actual_cast_chain_and_e03_tier_boundary(){
 let mut g=game();g.players[0].board.push(body(101,"BG25_039"));narrow(&mut g,"BG28_810");acquire(&mut g,CAPE);let before=g.players[0].stats.spells_cast;g.start_turn();assert_eq!(g.players[0].stats.spells_cast,before+2);assert!(g.players[0].hand.is_empty());
 let mut above=game();above.players[0].board.push(body(101,"BG23_004"));let card=*above.spell_universe.iter().find(|id|db().get(**id).tier>1).unwrap();above.spell_universe=vec![card];above.players[0].tier=1;let rng=above.rng.clone();acquire(&mut above,CAPE);assert_eq!(above.players[0].stats.spells_cast,0);assert_eq!(above.rng,rng);
}
#[test]fn cape_legal_random_target_and_no_target_skip_frozen_helper_policy(){
 let mut g=game();g.players[0].board.extend([body(101,"BG23_004"),body(102,"BG23_004")]);narrow(&mut g,"BG28_503");acquire(&mut g,CAPE);let sum:i32=g.players[0].board.iter().map(|m|m.max_hp).sum();assert_eq!(sum,23);assert_eq!(g.players[0].stats.spells_cast,1);assert!(g.players[0].pending.is_empty());
 let mut none=game();none.players[0].board.push(body(101,"BG23_004"));narrow(&mut none,"BG28_604");let rng=none.rng.clone();acquire(&mut none,CAPE);assert_eq!(none.players[0].stats.spells_cast,0);assert_ne!(none.rng,rng);assert_eq!(none.players[0].board[0].max_hp,10);assert!(none.players[0].pending.is_empty());
}
