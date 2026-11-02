//! Cross-package contracts, numeric oracle from fixed target definitions/declared effects.
use taverngym::{Game,RulesConfig};
use taverngym::actions::Action;
use taverngym::cards::{cid,db,CardKind};
use taverngym::script::{script,implemented};
use taverngym::state::{Item,Minion,Pending,ShopSlot};
fn raw(g:&Game)->String{serde_json::to_string(g).unwrap()}
fn game()->Game{let mut g=Game::new(541,RulesConfig{num_players:2,lesser_trinket_turn:0,greater_trinket_turn:0,..RulesConfig::default()});for p in 0..2{g.apply(p,Action::Choose(0)).unwrap();}for p in &mut g.players{p.board.clear();p.hand.clear();p.powers.clear();p.pending.clear();p.effects.clear();p.quests.clear();p.trinkets.clear();p.rewards.clear();p.secrets.clear();p.stats=Default::default();p.gold=30;p.tier=6;p.skipping=false;}g}
fn body(g:&mut Game,id:&str)->Minion{let mut m=Minion::new(g.alloc_eid(),cid(id));m.set_stats(10,10);m}
fn add(g:&mut Game,id:&str)->u32{let m=body(g,id);let e=m.eid;g.players[0].board.push(m);e}
fn pair(g:&Game,i:usize)->(i32,i32){let m=&g.players[0].board[i];(m.atk,m.max_hp)}
fn same_action(g:&mut Game,c:&mut Game,a:Action){g.apply(0,a.clone()).unwrap();c.apply(0,a).unwrap();assert_eq!(raw(g),raw(c));}

#[test]fn all30_primary_ids_have_explicit_engine_binding_without_roster_change(){
 let ids=["BG23_002","BG23_002_G","BG26_505","BG26_505_G","BG36_622","BG36_622_G","BG36_921","BG36_921_G","BG27_514","BG27_514_G","BG31_920","BG31_920_G","BG32_835","BG32_835_G","BG33_319","BG33_319_G","BG31_035","BG31_035_G","BG31_925","BG31_925_G","BG35_921","BG35_921_G","BG32_837","BG32_837_G","BG34_925","BG34_925_G","BG36_508","BG36_508_G","BG22_HERO_007","BG22_HERO_007p"];
 assert_eq!(ids.len(),30);for id in ids {let c=cid(id);assert!(implemented(c),"{id}");if db().get(c).kind==CardKind::Hero {assert_eq!(db().get(c).hero_power,Some(cid("BG22_HERO_007p")));}else{assert!(script(c).is_some(),"{id}");}}
 assert!(script(cid("BG22_HERO_007p2")).unwrap().hero_power.is_some());
}
#[test]fn cagey_resolving_ruiner_lorewalker_and_counter_auras_remain_distinct(){
 let mut g=game();for id in ["BG36_508","BG36_622","BG31_035","BG35_921"]{add(&mut g,id);}g.players[0].trinkets.push(cid("BG30_MagicItem_422"));assert!(g.spell_universe.contains(&cid("BG28_845")));g.spell_universe.retain(|c|*c==cid("BG28_845"));
 let prefix=raw(&g);let mut c:Game=serde_json::from_str(&prefix).unwrap();same_action(&mut g,&mut c,Action::Activate(0));
 assert_eq!(pair(&g,0),(26,26));for i in 1..4 {assert_eq!(pair(&g,i),(18,18));}
 assert_eq!(g.players[0].stats.spells_cast,0);assert_eq!(g.players[0].stats.tavern_spells_cast,0);assert_eq!(g.players[0].stats.cards_played,0);assert_eq!(g.players[0].gold,29);
}
#[test]fn meditation_generation_then_fauna_uses_bonus_without_new_hand_casts(){
 let mut g=game();add(&mut g,"BGS_004");add(&mut g,"BG32_837");add(&mut g,"BGS_004");let source=add(&mut g,"BG32_835");g.with_recruit(0,|c|c.give_spellcraft(0,source));assert_eq!(g.players[0].hand[0].item.card(),cid("BG32_835t"));
 g.apply(0,Action::Play{hand:0,pos:0}).unwrap();assert_eq!(g.players[0].stats.spell_atk,1);assert_eq!(g.players[0].stats.spell_hp,1);assert_eq!(g.players[0].stats.spells_cast,1);
 let prefix=raw(&g);let mut c:Game=serde_json::from_str(&prefix).unwrap();same_action(&mut g,&mut c,Action::EndTurn);
 assert_eq!(pair(&g,0),(16,14));assert_eq!(pair(&g,2),(16,14));assert_eq!(g.players[0].stats.spells_cast,1);assert_eq!(g.players[0].stats.tavern_spells_cast,0);
}
#[test]fn siren_tavern_naga_target_triggers_ruiner_but_not_shaker_copy(){
 let mut g=game();add(&mut g,"BG36_622");add(&mut g,"BG26_505");let source=add(&mut g,"BG27_514");let m=body(&mut g,"BG23_004");let sid=g.alloc_eid();g.players[0].shop.clear();g.players[0].shop.push(ShopSlot::new(sid,Item::Minion(m)));
 g.with_recruit(0,|c|c.give_spellcraft(0,source));assert_eq!(g.players[0].hand[0].item.card(),cid("BG27_514t"));g.apply(0,Action::Play{hand:0,pos:0}).unwrap();
 let options=match g.players[0].pending.last().unwrap(){Pending::Target{options,..}=>options,_=>panic!("Siren real target menu")};let ix=options.iter().position(|e|*e==sid).unwrap();let prefix=raw(&g);let mut c:Game=serde_json::from_str(&prefix).unwrap();same_action(&mut g,&mut c,Action::Choose(ix));
 for i in 0..3{assert_eq!(pair(&g,i),(12,13));}assert_eq!(g.players[0].board[1].counter,0);assert_eq!(g.players[0].hand.len(),1);
 let copy=g.players[0].hand[0].item.as_minion().unwrap();assert_eq!(copy.card,cid("BG23_004"));assert_eq!((copy.atk,copy.max_hp),(10,10));assert_ne!(copy.eid,sid);
 assert_eq!(g.players[0].stats.cards_played,1);assert_eq!(g.players[0].stats.spells_cast,1);assert_eq!(g.players[0].stats.tavern_spells_cast,0);
}
#[test]fn tyrael_cost_two_public_target_crosses_azshara_threshold_once(){
 for (id,v) in [("BG36_356",50),("BG36_356_G",100)]{let mut g=game();add(&mut g,id);let target=add(&mut g,"BGS_004");g.players[0].hero=Some(cid("BG22_HERO_007"));g.players[0].set_hero_power(0,cid("BG22_HERO_007p"));g.players[0].gold=1;
  let before=raw(&g);assert!(g.apply(0,Action::Activate(0)).is_err());assert_eq!(raw(&g),before);g.players[0].gold=2;g.apply(0,Action::Activate(0)).unwrap();assert_eq!(g.players[0].gold,2);
  let options=match g.players[0].pending.last().unwrap(){Pending::Target{options,..}=>options,_=>panic!("Tyrael real target menu")};let ix=options.iter().position(|e|*e==target).unwrap();let prefix=raw(&g);let mut c:Game=serde_json::from_str(&prefix).unwrap();same_action(&mut g,&mut c,Action::Choose(ix));
  assert_eq!(pair(&g,1),(v,v));assert_eq!(g.players[0].gold,0);assert_eq!(g.players[0].powers[0].card,cid("BG22_HERO_007p2"));assert_eq!(g.players[0].hero,Some(cid("BG22_HERO_007t")));
 }
}
