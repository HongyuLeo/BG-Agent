use taverngym::{Game,RulesConfig};
use taverngym::actions::Action;
use taverngym::cards::{cid,db};
fn raw(g:&Game)->String{serde_json::to_string(g).unwrap()}
fn setup(id:&str,tier:u8,candidates:&[&str])->Game{
 let mut g=Game::new(17,RulesConfig{num_players:2,record_log:true,..RulesConfig::default()});
 for p in 0..2{g.apply(p,Action::Choose(0)).unwrap();}
 for p in &mut g.players{p.pending.clear();p.board.clear();p.hand.clear();p.shop.clear();p.powers.clear();p.trinkets.clear();p.effects.clear();p.quests.clear();p.counters.clear();p.stats=Default::default();p.gold=20;p.tier=tier;p.skipping=false;}
 g.cfg.triple_copies=99;
 g.with_recruit(0,|c|c.give_card(0,cid(id)));
 g.apply(0,Action::Play{hand:0,pos:0}).unwrap();
 g.players[0].hand.retain(|h|h.item.card()!=cid("TB_BaconShop_Triples_01"));
 assert_eq!(g.players[0].hand.len(),1);
 for id in candidates{assert!(g.spell_universe.contains(&cid(id)),"only narrow pre-existing universe");}
 g.spell_universe.retain(|c|candidates.iter().any(|id|cid(id)==*c));g
}
fn check(id:&str,n:usize,tier:u8,candidates:&[&str],expected:Option<&str>){
 let mut g=setup(id,tier,candidates);let universe=g.spell_universe.clone();let rng=serde_json::to_string(&g.rng).unwrap();let mut copied=g.clone();let mut restored:Game=serde_json::from_str(&raw(&g)).unwrap();
 for branch in [&mut g,&mut copied,&mut restored]{branch.apply(0,Action::Play{hand:0,pos:1}).unwrap();}
 assert_eq!(raw(&g),raw(&copied));assert_eq!(raw(&g),raw(&restored));assert_eq!(g.spell_universe,universe);
 if let Some(expected)=expected{assert_eq!(g.players[0].hand.len(),n);for h in &g.players[0].hand{assert_eq!(h.item.card(),cid(expected));assert!(db().get(h.item.card()).tier<=tier);}}
 else{assert!(g.players[0].hand.is_empty());assert_eq!(serde_json::to_string(&g.rng).unwrap(),rng,"empty eligible set must not consume RNG");}
}
macro_rules! cases{($high:ident,$same:ident,$low:ident,$mixed:ident,$empty:ident,$id:literal,$n:literal)=>{
 #[test]fn $high(){assert_eq!(db().get(cid("BG28_520")).tier,3);check($id,$n,1,&["BG28_520"],None);}
 #[test]fn $same(){assert_eq!(db().get(cid("BG28_503")).tier,1);check($id,$n,1,&["BG28_503"],Some("BG28_503"));}
 #[test]fn $low(){check($id,$n,3,&["BG28_503"],Some("BG28_503"));}
 #[test]fn $mixed(){check($id,$n,1,&["BG28_503","BG28_520"],Some("BG28_503"));}
 #[test]fn $empty(){check($id,$n,1,&[],None);}
}}
cases!(normal_high_blocked,normal_same_allowed,normal_low_allowed,normal_mixed_excludes_high,normal_empty_no_rng,"BG33_319",1);
cases!(gold_high_blocked,gold_same_allowed,gold_low_allowed,gold_mixed_excludes_high,gold_empty_no_rng,"BG33_319_G",2);
#[test]fn explicit_tier_generation_api_still_overrides_owner_tier(){
 let mut g=setup("BG33_319",1,&["BG28_520"]);let mut selected=None;
 g.with_recruit(0,|c|{selected=c.random_spell(|d|d.tier==3);});
 assert_eq!(selected,Some(cid("BG28_520")),"shared explicit-tier API remains unchanged; this is an API control, not card admission");
}
