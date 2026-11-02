use taverngym::{Game,RulesConfig,Action};
use taverngym::cards::{cid,db};
use taverngym::script::script;
use taverngym::state::{Pending,HeroPowerState};
include!("maxwell_mapping_oracle.inc");
fn game(hero:&str,power:&str)->Game {
 let mut g=Game::new(977,RulesConfig{num_players:2,triple_copies:99,lesser_trinket_turn:0,greater_trinket_turn:0,..RulesConfig::default()});
 for p in 0..2 {g.apply(p,Action::Choose(0)).unwrap();}
 for p in &mut g.players {p.pending.clear();p.hand.clear();p.board.clear();p.shop.clear();p.trinkets.clear();p.effects.clear();p.quests.clear();p.gold=30;p.skipping=false;}
 g.players[0].hero=Some(cid(hero));g.players[0].powers=vec![HeroPowerState::new(cid(power))];g
}
fn offer(g:&mut Game,id:&str){g.players[0].pending.push(Pending::Trinket{options:vec![cid(id)],free:false,replace:None});}
fn raw(g:&Game)->String{serde_json::to_string(g).unwrap()}
#[test]fn exact_two_scripts_have_acquisition_hooks(){for id in ["BG35_MagicItem_803","BG35_MagicItem_803t"]{assert!(script(cid(id)).and_then(|s|s.on_attach).is_some(),"missing Maxwell callback {id}");}}
#[test]fn all_current116_heroes_actual_public_acquisition_or_explicit_unknown_failure(){
 assert_eq!(MAP.len(),116);let mut mapped=0;let mut unknown=0;
 for &(hero,power,buddy,gold) in MAP {for (id,want) in [("BG35_MagicItem_803",buddy),("BG35_MagicItem_803t",gold)] {
  let mut g=game(hero,power);offer(&mut g,id);let before=raw(&g);let result=g.apply(0,Action::Choose(0));
  if let Some(want)=want {result.unwrap();assert_eq!(g.players[0].hand.len(),1,"{hero} {id}");assert_eq!(g.players[0].hand[0].item.card(),cid(want));assert_eq!(g.players[0].trinkets,vec![cid(id)]);assert_eq!(g.players[0].gold,30-db().get(cid(id)).cost);mapped+=1;}
  else {assert!(result.is_err(),"unknown Buddy mapping must fail explicitly for {hero}");assert_eq!(raw(&g),before);unknown+=1;}
 }}assert_eq!(mapped,214);assert_eq!(unknown,18);
}
#[test]fn current_primary_power_not_original_hero_or_secondary_power(){
 let a=MAP.iter().find(|r|r.2.is_some()).unwrap();let b=MAP.iter().find(|r|r.2.is_some()&&r.2!=a.2).unwrap();
 let mut g=game(a.0,b.1);g.players[0].powers.push(HeroPowerState::new(cid(a.1)));offer(&mut g,"BG35_MagicItem_803");g.apply(0,Action::Choose(0)).unwrap();assert_eq!(g.players[0].hand[0].item.card(),cid(b.2.unwrap()));
 // Primary is an explicitly documented Player contract; never fall back to a known secondary.
 let u=MAP.iter().find(|r|r.2.is_none()).unwrap();let mut g=game(a.0,u.1);g.players[0].powers.push(HeroPowerState::new(cid(a.1)));offer(&mut g,"BG35_MagicItem_803");let before=raw(&g);assert!(g.apply(0,Action::Choose(0)).is_err());assert_eq!(before,raw(&g));
}
#[test]fn transformed_azshara_power_uses_actual_same_buddy_relation(){for hero in ["BG22_HERO_007","BG22_HERO_007t"] {for id in ["BG35_MagicItem_803","BG35_MagicItem_803t"] {let power=db().get(cid(hero)).hero_power.unwrap();let mut g=game(hero,&db().get(power).id);offer(&mut g,id);g.apply(0,Action::Choose(0)).unwrap();let b=db().get(cid(hero)).buddy.unwrap();let expected=if id.ends_with("803t"){db().get(b).golden.unwrap()}else{b};assert_eq!(g.players[0].hand[0].item.card(),expected);}}}
#[test]fn full_raw_copy_restore_identical_public_purchase_and_generated_play(){
 let a=MAP.iter().find(|r|r.2.is_some()).unwrap();for id in ["BG35_MagicItem_803","BG35_MagicItem_803t"] {let mut g=game(a.0,a.1);offer(&mut g,id);let before=raw(&g);let mut c=g.clone();let mut r:Game=serde_json::from_str(&before).unwrap();r.check_loaded().unwrap();assert_eq!(raw(&c),before);assert_eq!(raw(&r),before);for x in [&mut g,&mut c,&mut r] {x.apply(0,Action::Choose(0)).unwrap();x.apply(0,Action::Play{hand:0,pos:0}).unwrap();}assert_eq!(raw(&g),raw(&c));assert_eq!(raw(&g),raw(&r));}
}
#[test]fn unknown_power_and_missing_power_refuse_without_payment(){for powers in [vec![],vec![HeroPowerState::new(cid("BG28_810"))]] {let mut g=game(MAP[0].0,MAP[0].1);g.players[0].powers=powers;offer(&mut g,"BG35_MagicItem_803t");let before=raw(&g);assert!(g.apply(0,Action::Choose(0)).is_err());assert_eq!(before,raw(&g));}}
#[test]fn transformed_azshara_real_unsupported_dependency_is_explicit_and_atomic(){
 for hero in ["BG22_HERO_007","BG22_HERO_007t"] {for id in ["BG35_MagicItem_803","BG35_MagicItem_803t"] {
  let h=db().get(cid(hero));let buddy=h.buddy.unwrap();let buddy=if id.ends_with("803t"){db().get(buddy).golden.unwrap()}else{buddy};
  assert!(!taverngym::script::implemented(buddy),"existing dependency gap must not be hidden");
  let mut g=game(hero,&db().get(h.hero_power.unwrap()).id);offer(&mut g,id);let before=raw(&g);
  assert_eq!(g.apply(0,Action::Choose(0)),Err("Maxwell: exact associated Buddy effect is unsupported"));assert_eq!(raw(&g),before);
 }}
}
