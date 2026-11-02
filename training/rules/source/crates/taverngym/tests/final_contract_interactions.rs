use taverngym::{Game,RulesConfig};
use taverngym::actions::Action;
use taverngym::cards::{cid,db,CardKind};
use taverngym::state::{Minion,Item,Pending,ShopSlot};
fn game()->Game{let mut g=Game::new(991,RulesConfig{num_players:2,record_log:true,..Default::default()});for p in 0..2{g.apply(p,Action::Choose(0)).unwrap();}for p in &mut g.players{p.pending.clear();p.hand.clear();p.board.clear();p.shop.clear();p.powers.clear();p.effects.clear();p.quests.clear();p.trinkets.clear();p.counters.clear();p.stats=Default::default();p.gold=30;p.tier=6;p.skipping=false;}g.next_eid=100;g.cfg.triple_copies=99;g}
fn raw(g:&Game)->String{serde_json::to_string(g).unwrap()}
fn give(g:&mut Game,id:&str){g.with_recruit(0,|c|{c.give_card(0,cid(id));});}
fn play(g:&mut Game,i:usize){let pos=g.players[0].board.len();g.apply(0,Action::Play{hand:i,pos}).unwrap();}
fn pick_target(g:&mut Game,e:u32){let Some(Pending::Target{options,..})=g.players[0].pending.last()else{panic!("missing target")};let i=options.iter().position(|x|*x==e).unwrap();g.apply(0,Action::Choose(i)).unwrap();}
fn discover(g:&mut Game,id:&str){g.universe.clear();g.spell_universe.clear();if db().get(cid(id)).kind==CardKind::Minion{g.universe.push(cid(id));g.pool.put(cid(id),5);}else{g.spell_universe.push(cid(id));}give(g,"BG31_892");let i=g.players[0].hand.len()-1;play(g,i);g.apply(0,Action::Choose(0)).unwrap();}
fn queued()->Game{let mut g=game();g.players[0].trinkets.push(cid("BG30_MagicItem_801"));for _ in 0..9{give(&mut g,"BG20_GEM");}discover(&mut g,"BG32_237");assert_eq!(g.players[0].hand.len(),10);assert_eq!(g.players[0].hand_queue.len(),1);assert!(g.players[0].hand_queue_marks[0].combined);g}
#[test]fn queued_combined_copy_then_public_purchase_preserves_marker_and_scoped_gold_counter(){
 let mut g=queued();let mut pirate=Minion::new(301,cid("BG26_810"));pirate.counter=4;g.players[0].board.push(pirate);g.players[1].board.push(Minion::new(302,cid("BG26_810")));g.players[0].shop.push(ShopSlot::new(303,Item::Minion(Minion::new(303,cid("BGS_115")))));
 let before=raw(&g);let mut clone=g.clone();let mut restored:Game=serde_json::from_str(&before).unwrap();
 for b in [&mut g,&mut clone,&mut restored]{play(b,9);assert!(b.players[0].pending.is_empty());assert!(b.players[0].hand_queue.is_empty());assert!(b.players[0].hand[9].combined);play(b,9);assert!(b.players[0].pending.is_empty());assert_eq!((b.players[0].stats.spell_atk,b.players[0].stats.spell_hp),(2,2));b.apply(0,Action::Buy(0)).unwrap();let m=b.players[0].board.iter().find(|m|m.eid==301).unwrap();let base=db().get(cid("BG26_810"));assert_eq!((m.counter,m.atk,m.max_hp),(0,base.atk+3,base.hp+1));assert_eq!(b.players[1].board[0].counter,0);}
 assert_eq!(raw(&g),raw(&clone));assert_eq!(raw(&g),raw(&restored));
}
#[test]fn legacy_native_queue_mark_missing_combined_defaults_false_without_normalizing_other_fields(){
 let g=queued();let original=raw(&g);let mut old:serde_json::Value=serde_json::from_str(&original).unwrap();old["players"][0]["hand_queue_marks"][0].as_object_mut().unwrap().remove("combined");let restored:Game=serde_json::from_value(old).unwrap();let mut expected=g.clone();expected.players[0].hand_queue_marks[0].combined=false;assert_eq!(raw(&restored),raw(&expected));assert_eq!(raw(&g),original);assert!(g.players[0].hand_queue_marks[0].combined);
}
#[test]fn combined_targeted_spell_copy_and_eonar_dual_type_selection_remain_card_local(){
 let mut g=game();g.players[0].board.push(Minion::new(311,cid("BG25_039")));let base=(g.players[0].board[0].atk,g.players[0].board[0].max_hp);g.players[0].trinkets.push(cid("BG30_MagicItem_801"));discover(&mut g,"BG31_886");assert_eq!(g.players[0].hand.len(),2);play(&mut g,0);pick_target(&mut g,311);assert!(g.players[0].pending.is_empty());assert_eq!((g.players[0].board[0].atk,g.players[0].board[0].max_hp),(base.0+14,base.1+14));assert!(g.players[0].hand[0].combined);
 give(&mut g,"BG35_912");let types:Vec<_>=g.players[0].board[0].races.iter().collect();assert_eq!(types.len(),2);let mut rng=g.rng.clone();let expected=rng.pick(&types).unwrap().0;play(&mut g,1);let mut twin:Game=serde_json::from_str(&raw(&g)).unwrap();for b in [&mut g,&mut twin]{pick_target(b,311);assert_eq!(b.players[0].stats.tavern_race,vec![(expected,3,3)]);assert_eq!(b.rng,rng);assert!(b.players[0].hand[0].combined);}assert_eq!(raw(&g),raw(&twin));
}
