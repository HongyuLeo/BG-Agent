use taverngym::{Game, RulesConfig};
use taverngym::actions::{Action, A_HERO_POWER};
use taverngym::cards::{cid, db};
use taverngym::script::{script, Shown};
use taverngym::state::Pending;
use taverngym::types::Races;
const HERO: &str="BG22_HERO_007";
const POWER: &str="BG22_HERO_007p";
const QUEEN: &str="BG22_HERO_007t";
const CONQUEST: &str="BG22_HERO_007p2";
fn game() -> Game {
 let mut g=Game::new(220007,RulesConfig {num_players:2, hero_choices:1, experimental_mode:true,
 hero_pool:vec!["TB_BaconShop_HERO_34".into(),"TB_BaconShop_HERO_20".into()],
 lobby_types:vec!["NAGA".into(),"PIRATE".into(),"DRAGON".into(),"BEAST".into(),"MURLOC".into()],
 timewarp_turns:[0,0], lesser_trinket_turn:0, greater_trinket_turn:0,..RulesConfig::default()});
 for p in 0..2 {g.apply(p,Action::Choose(0)).unwrap();g.players[p].pending.clear();g.players[p].board.clear();g.players[p].powers.clear();}
 for p in 0..2 {g.players[p].pending.clear();g.players[p].board.clear();g.players[p].powers.clear();}
 g.players[0].hero=Some(cid(HERO));g.players[0].health=23;g.players[0].armor=7;g.players[0].gold=10;
 g.set_hero_power(0,0,cid(POWER));g
}
fn board(g:&mut Game, atk:i32) -> u32 {
 let m=g.with_recruit(0,|c|{let mut m=c.new_minion(0,cid("BG25_001"));m.set_stats(atk,100);m});
 let id=m.eid;g.players[0].board=vec![m];id
}
fn transformed(g:&Game) { assert_eq!(g.players[0].hero,Some(cid(QUEEN)));assert_eq!(g.players[0].hero_power(),Some(cid(CONQUEST)));assert_eq!((g.players[0].health,g.players[0].armor),(23,7)); }
#[test] fn azshara_registered_with_real_dependencies(){assert!(script(cid(POWER)).is_some());assert!(script(cid(CONQUEST)).unwrap().hero_power.is_some());assert_eq!(db().get(cid(QUEEN)).hero_power,Some(cid(CONQUEST)));assert_eq!(db().get(cid(CONQUEST)).cost,1);}
#[test] fn azshara_29_attack_not_health_then_exact_30() {
 let mut g=game();let eid=board(&mut g,29);g.with_recruit(0,|_|{});
 assert_eq!(g.players[0].hero_power(),Some(cid(POWER)));assert!(!g.legal_mask(0)[A_HERO_POWER]);
 g.with_recruit(0,|c|{let sh=Shown{side:0,card:cid(POWER),golden:false,minion:None,data:0};assert_eq!(script(cid(POWER)).unwrap().shown.unwrap()(c,&sh),vec![30]);c.buff(eid,1,0);assert_eq!(c.player_ref(0).unwrap().hero_power(),Some(cid(CONQUEST)));});
 transformed(&g);let o=taverngym::obs::observe(&g,0);assert_eq!(o.cards[0],cid(QUEEN).idx() as i32+1);assert_eq!(o.cards[1],cid(CONQUEST).idx() as i32+1);assert!(g.legal_mask(0)[A_HERO_POWER]);
}
#[test] fn azshara_temporary_recruit_buff_and_set_stats_transform(){for temp in [true,false]{let mut g=game();let e=board(&mut g,29);g.with_recruit(0,|c|if temp{c.buff_temp(e,1,0)}else{c.set_stats(e,30,100)});transformed(&g);}}
#[test] fn azshara_attach_at_threshold_and_reentry_keep_uses(){let mut g=game();board(&mut g,30);g.set_hero_power(0,0,cid(POWER));transformed(&g);g.players[0].powers[0].uses_turn=1;g.with_recruit(0,|c|{c.bump_player_stat(0,|_|{});});assert_eq!(g.players[0].powers[0].uses_turn,1);assert!(!g.legal_mask(0)[A_HERO_POWER]);}
#[test] fn azshara_dead_and_opponent_attack_excluded(){let mut g=game();board(&mut g,29);g.players[0].board[0].hp=0;g.with_recruit(0,|c|c.bump_player_stat(0,|_|{}));assert_eq!(g.players[0].hero_power(),Some(cid(POWER)));let m=g.with_recruit(1,|c|{let mut m=c.new_minion(0,cid("BG25_001"));m.set_stats(100,100);m});g.players[1].board.push(m);g.with_recruit(1,|_|{});assert_eq!(g.players[0].hero_power(),Some(cid(POWER)));}
#[test] fn azshara_combat_temporary_attack_does_not_unlock(){let mut g=game();let e=board(&mut g,29);let boards=[g.players[0].board.clone(),vec![]];let mut c=taverngym::engine::Ctx::new(&mut g,boards,[Some(0),Some(1)],true);c.buff_temp(e,1,0);assert_eq!(c.player_ref(0).unwrap().hero_power(),Some(cid(POWER)));}
#[test] fn azshara_copy_restore_raw_rng_and_discover_pool(){let mut g=game();board(&mut g,30);g.with_recruit(0,|_|{});transformed(&g);let raw=serde_json::to_string(&g).unwrap();let mut restored:Game=serde_json::from_str(&raw).unwrap();let mut cloned=g.clone();for run in [&mut g,&mut restored,&mut cloned]{assert_eq!(run.hero_power_price(0,0),Some(1));let gold=run.players[0].gold;run.apply(0,Action::HeroPower(0)).unwrap();assert_eq!(run.players[0].gold,gold-1);assert!(!run.players[0].pending.is_empty());if let Some(Pending::Discover{options,..})=run.players[0].pending.last(){assert!(!options.is_empty());for option in options {assert!(db().get(option.card()).races.intersects(Races::NAGA));}}else{panic!("expected real Discover")};run.apply(0,Action::Choose(0)).unwrap();assert!(!run.legal_mask(0)[A_HERO_POWER]);}assert_eq!(serde_json::to_string(&g).unwrap(),serde_json::to_string(&restored).unwrap());assert_eq!(serde_json::to_string(&g).unwrap(),serde_json::to_string(&cloned).unwrap());}

#[test] fn azshara_real_summon_crosses_threshold_without_rng_draw(){let mut g=game();board(&mut g,29);let rng=serde_json::to_string(&g.rng).unwrap();g.with_recruit(0,|c|{let mut m=c.new_minion(0,cid("BG25_001"));m.set_stats(1,1);c.summon(0,1,m).unwrap();});transformed(&g);assert_eq!(serde_json::to_string(&g.rng).unwrap(),rng);}
#[test] fn azshara_extra_slot_changes_only_that_slot_not_other_hero(){let mut g=game();g.players[0].hero=Some(cid("TB_BaconShop_HERO_34"));g.players[0].powers.clear();g.set_hero_power(0,0,cid("TB_BaconShop_HP_063"));g.players[0].powers[0].uses_game=7;g.set_hero_power(0,1,cid(POWER));let other=serde_json::to_string(&g.players[1]).unwrap();let first=serde_json::to_string(&g.players[0].powers[0]).unwrap();board(&mut g,30);g.with_recruit(0,|_|{});assert_eq!(g.players[0].hero,Some(cid("TB_BaconShop_HERO_34")));assert_eq!(g.players[0].powers[1].card,cid(CONQUEST));assert_eq!(serde_json::to_string(&g.players[0].powers[0]).unwrap(),first);assert_eq!(serde_json::to_string(&g.players[1]).unwrap(),other);}
#[test] fn azshara_discover_pool_and_empty_no_rng(){let mut g=game();board(&mut g,30);g.with_recruit(0,|_|{});g.players[0].tier=6;
 let cands:Vec<_>=g.universe.iter().copied().filter(|x|db().get(*x).races.intersects(Races::NAGA)&&g.pool.get(*x)>0).collect();assert!(!cands.is_empty());
 let rng=serde_json::to_string(&g.rng).unwrap();for x in &cands{g.pool.counts[x.idx()]=0;}g.apply(0,Action::HeroPower(0)).unwrap();assert!(g.players[0].pending.is_empty());assert_eq!(serde_json::to_string(&g.rng).unwrap(),rng);
 // Component setup narrows the real universe to one already eligible identity.
 g.players[0].powers[0].uses_turn=0;let chosen=cands[0];g.pool.put(chosen,1);g.apply(0,Action::HeroPower(0)).unwrap();let options=match g.players[0].pending.last().unwrap(){Pending::Discover{options,..}=>options,_=>panic!()};assert_eq!(options.len(),1);assert_eq!(options[0].card(),chosen);g.apply(0,Action::Choose(0)).unwrap();assert_eq!(g.pool.get(chosen),0);
}
#[test] fn azshara_universe_eligibility_unchanged_on_transform(){let mut g=game();let universe=g.universe.clone();let spells=g.spell_universe.clone();let pool=g.pool.clone();let races=g.lobby_races;board(&mut g,30);g.with_recruit(0,|_|{});assert_eq!(g.universe,universe);assert_eq!(g.spell_universe,spells);assert_eq!(g.pool,pool);assert_eq!(g.lobby_races,races);}
#[test] fn azshara_public_spell_play_crosses_threshold_with_real_target_menu(){let mut g=game();let e=board(&mut g,29);g.players[0].hand.clear();g.with_recruit(0,|c|{c.add_to_hand(0,taverngym::state::Item::spell(cid("BG_TB_006")));});g.apply(0,Action::Play{hand:0,pos:0}).unwrap();let ix=match g.players[0].pending.last().unwrap(){Pending::Target{options,..}=>options.iter().position(|x|*x==e).unwrap(),_=>panic!("missing target menu")};g.apply(0,Action::Choose(ix)).unwrap();transformed(&g);}
#[test] fn azshara_high_tier_naga_never_offered_at_tier_one(){let mut g=game();board(&mut g,30);g.with_recruit(0,|_|{});g.players[0].tier=1;for c in g.universe.clone(){if db().get(c).races.intersects(Races::NAGA)&&db().get(c).tier<=1{g.pool.counts[c.idx()]=0;}}let rng=serde_json::to_string(&g.rng).unwrap();g.apply(0,Action::HeroPower(0)).unwrap();assert!(g.players[0].pending.is_empty());assert_eq!(serde_json::to_string(&g.rng).unwrap(),rng);}
