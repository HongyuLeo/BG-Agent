use taverngym::{Game,RulesConfig};
use taverngym::cards::{cid,db};
use serde_json::{json,Value};
#[test]
fn named_target_roster_is_an_actual_constructor_input() {
 let cfg=json!({"target_roster":{"manifest_sha256":"0000000000000000000000000000000000000000000000000000000000000000","manifest":{"ruleset_id":"test","target_build":"37","source_qualified":true,"public_offer":{"minion":[],"tavern_spell":[],"hero":[],"trinket":[]},"supported_derived":[],"excluded":[],"source_unknown":[],"derived_parents":[]}}});
 let result=RulesConfig::from_json(&cfg.to_string());
 assert!(!result.as_ref().err().is_some_and(|e|e.contains("unknown field \"target_roster\"")),"no target roster application entry: {:?}",result.err());
}
fn fixture()->Value {serde_json::from_str(include_str!("fixtures/target_roster.json")).unwrap()}
fn config(roster:Value)->Value {json!({"num_players":2,"hero_choices":1,"guaranteed_heroes":[],"lobby_races":1,"lobby_types":["NAGA"],"target_roster":roster})}
fn seal(v:&mut Value) {let r:taverngym::roster::TargetRoster=serde_json::from_value(v["target_roster"].clone()).unwrap();v["target_roster"]["manifest_sha256"]=json!(r.digest());}
fn construct(v:&Value)->Game {Game::new(17,RulesConfig::from_json(&v.to_string()).unwrap())}
#[test]
fn python_sha256_fixture_matches_native_canonical_digest_and_explicit_universes() {
 let r:taverngym::roster::TargetRoster=serde_json::from_value(fixture()).unwrap();assert_eq!(r.digest(),r.manifest_sha256);
 let g=construct(&config(fixture()));assert_eq!(g.universe,vec![cid("BG23_000")]);assert_eq!(g.spell_universe,vec![cid("BG28_168")]);assert_eq!(g.trinket_universe,vec![cid("BG30_MagicItem_801")]);assert!(!g.universe.contains(&cid("BG23_000_G")));assert!(!g.universe.contains(&cid("BG31_920")));assert!(!g.universe.contains(&cid("BG23_004")));
}
#[test]
fn manifest_never_enables_a_type_and_existing_hero_lobby_bans_still_apply() {
 let mut v=config(fixture());v["lobby_types"]=json!(["ABERRATION"]);let g=construct(&v);assert!(!g.universe.contains(&cid("BG23_000")));for p in &g.players {let taverngym::state::Pending::HeroSelect{options}=&p.pending[0] else{panic!()};assert!(!options.contains(&cid("BG34_HERO_004")));}
}
#[test]
fn digest_overlap_unknown_golden_unsupported_and_force_override_fail_visibly() {
 let mut cases=Vec::new();let mut bad=config(fixture());bad["target_roster"]["manifest_sha256"]=json!("0".repeat(64));cases.push(bad);
 for (path,id) in [("minion","BG23_000"),("minion","BG23_000_G"),("minion","NOT_A_CARD"),("minion","AT_121")] {let mut v=config(fixture());v["target_roster"]["manifest"]["public_offer"][path].as_array_mut().unwrap().push(json!(id));seal(&mut v);cases.push(v);}
 let mut v=config(fixture());v["hero_pool"]=json!(["BG34_HERO_004"]);cases.push(v);
 let mut v=config(fixture());v["target_roster"]["manifest"]["source_qualified"]=json!(false);seal(&mut v);cases.push(v);
 let mut v=config(fixture());v["target_roster"]["manifest"]["public_offer"]["minion"].as_array_mut().unwrap().push(json!("BG31_920"));seal(&mut v);cases.push(v);
 for (i,v) in cases.iter().enumerate(){assert!(RulesConfig::from_json(&v.to_string()).is_err(),"accepted invalid case {i}");}
}
#[test]
fn none_preserves_original_serialized_config_and_exact_state_rng_replay() {
 let original=RulesConfig::from_json("{}").unwrap();assert!(serde_json::to_value(&original).unwrap().get("target_roster").is_none());
 let a=Game::new(97,original);let b=Game::new(97,RulesConfig::from_json("{\"target_roster\":null}").unwrap());assert_eq!(serde_json::to_string(&a).unwrap(),serde_json::to_string(&b).unwrap());
 let g=construct(&config(fixture()));let raw=serde_json::to_string(&g).unwrap();let copy:Game=serde_json::from_str(&raw).unwrap();assert_eq!(serde_json::to_string(&copy).unwrap(),raw);
 let roster=copy.cfg.target_roster.as_ref().unwrap();assert_eq!(roster.digest(),roster.manifest_sha256);
}
#[test]
fn target_trinket_exclusion_is_honored_without_changing_legacy_path() {let mut v=config(fixture());v["excluded_cards"]=json!(["BG30_MagicItem_801"]);let g=construct(&v);assert!(g.trinket_universe.is_empty());}
#[test]
fn denied_gift_pair_is_an_actual_native_candidate_filter_with_neighbor_control() {
 let roster:Value=serde_json::from_str(include_str!("fixtures/target_roster_pairs.json")).unwrap();let mut g=construct(&config(roster));
 g.with_recruit(0,|c|{let gift=cid("BG36_MidGameEffect_000t16");for id in ["BG23_318","BG23_318_G"] {assert!(!taverngym::content::gift_fits(c,0,gift,db().get(cid(id)),1),"denied pair allowed {id}");}assert!(taverngym::content::gift_fits(c,0,gift,db().get(cid("BG19_010")),1));});
 let mut legacy=Game::new(17,RulesConfig::default());legacy.with_recruit(0,|c|assert!(taverngym::content::gift_fits(c,0,cid("BG36_MidGameEffect_000t16"),db().get(cid("BG23_318")),1)));
}
#[test]
fn uninstalled_source_unknown_is_metadata_not_a_public_bypass_and_disabled_parent_stays_inactive() {
 let mut v=config(fixture());v["target_roster"]["manifest"]["source_unknown"].as_array_mut().unwrap().push(json!("UNINSTALLED_ANOMALY_ID"));seal(&mut v);assert!(RulesConfig::from_json(&v.to_string()).is_ok());
 v["target_roster"]["manifest"]["public_offer"]["minion"].as_array_mut().unwrap().push(json!("UNINSTALLED_ANOMALY_ID"));seal(&mut v);assert!(RulesConfig::from_json(&v.to_string()).is_err());
 let mut v=config(fixture());v["target_roster"]["manifest"]["public_offer"]["minion"]=json!([]);v["target_roster"]["manifest"]["excluded"].as_array_mut().unwrap().push(json!("BG23_000"));seal(&mut v);let cfg=RulesConfig::from_json(&v.to_string()).unwrap();assert!(!cfg.target_roster.as_ref().unwrap().parent_route_allowed("BG23_000","BG23_000_G"));
}
#[test]
fn invalid_exact_gift_pair_type_identity_and_duplicate_reject() {
 for pairs in [json!([{"minion":"BG23_318","gift":"NOT_A_GIFT"}]),json!([{"minion":"BG28_168","gift":"BG36_MidGameEffect_000t16"}]),json!([{"minion":"BG23_318","gift":"BG36_MidGameEffect_000t16"},{"minion":"BG23_318","gift":"BG36_MidGameEffect_000t16"}])] {let mut v=config(fixture());v["target_roster"]["manifest"]["denied_gift_pairs"]=pairs;seal(&mut v);assert!(RulesConfig::from_json(&v.to_string()).is_err());}
}
#[test]
fn actual_mukla_producer_and_bg_banana_effect_keep_exact_identity_through_restore() {
 use taverngym::actions::Action;
 let cfg=RulesConfig::from_json("{\"num_players\":2,\"hero_choices\":1,\"hero_pool\":[\"TB_BaconShop_HERO_38\"],\"guaranteed_heroes\":[]}").unwrap();let mut g=Game::new(17,cfg);
 for p in 0..2 {g.apply(p,Action::Choose(0)).unwrap();}
 let token=cid("BG_EX1_014t");let hand=g.players[0].hand.iter().position(|h|h.item.card()==token).expect("fixed producer prefix yielded no ordinary Banana");assert!(db().find("EX1_014t").is_none());
 let target=g.with_recruit(0,|c|{let m=c.new_minion(0,cid("BG23_000"));let id=m.eid;c.boards[0].push(m);id});let m=&g.players[0].board[0];let before=(m.atk,m.max_hp);let raw=serde_json::to_string(&g).unwrap();let mut restored:Game=serde_json::from_str(&raw).unwrap();assert_eq!(serde_json::to_string(&restored).unwrap(),raw);assert_eq!(restored.players[0].hand[hand].item.card(),token);
 for state in [&mut g,&mut restored] {state.apply(0,Action::Play{hand,pos:0}).unwrap();let taverngym::state::Pending::Target{options,..}=state.players[0].pending.last().unwrap()else{panic!()};let i=options.iter().position(|id|*id==target).unwrap();state.apply(0,Action::Choose(i)).unwrap();assert_eq!((state.players[0].board[0].atk,state.players[0].board[0].max_hp),(before.0+1,before.1+1));}
 assert_eq!(serde_json::to_string(&g).unwrap(),serde_json::to_string(&restored).unwrap());
}
#[test]
fn version_identity_record_binds_exact_execution_dbf_without_creating_an_alias() {
 let mut v=config(fixture());v["target_roster"]["manifest"]["supported_derived"].as_array_mut().unwrap().push(json!("BG_EX1_014t"));
 v["target_roster"]["manifest"]["execution_identity_bindings"]=json!([{"source_parent":"TB_BaconShop_HERO_38","source_power":"TB_BaconShop_HP_038","source_child_id":"EX1_014t","source_child_dbf":1694,"execution_child_id":"BG_EX1_014t","execution_child_dbf":122906,"decision_sha256":"70d124053eb457b2994c0058735698f7abbfd4b6fbee0fa49fd278acd43676bb","evidence_sha256":"56b5b01d500ccb1128caae7a51f6b507ddab6cedaff062446b70a81cc2ca0fb3"}]);seal(&mut v);assert!(RulesConfig::from_json(&v.to_string()).is_ok());assert!(db().find("EX1_014t").is_none());assert_eq!(db().get(cid("BG_EX1_014t")).dbf,122906);
 v["target_roster"]["manifest"]["execution_identity_bindings"][0]["execution_child_dbf"]=json!(1694);seal(&mut v);assert!(RulesConfig::from_json(&v.to_string()).is_err());
}
