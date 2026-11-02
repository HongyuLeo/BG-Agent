//! Evidence for named frozen native routes only, not universal reachability proof.
use taverngym::{Action,Game,RulesConfig};
use taverngym::cards::{cid,db};
use taverngym::state::Pending;

#[test]fn frozen_shared_pools_and_real_finley_menu_do_not_offer_azshara() {
    let ambition=cid("BG22_HERO_007p");let conquest=cid("BG22_HERO_007p2");let buddy=cid("BG22_HERO_007_Buddy");
    // Exhaust the full metadata producer roots, before any lobby-type filtering.
    let hero_roots:Vec<_>=db().iter().filter(|c|c.pools.hero).collect();assert!(!hero_roots.is_empty());
    for h in &hero_roots {assert_ne!(h.hero_power,Some(ambition));assert_ne!(h.hero_power,Some(conquest));assert_ne!(h.buddy,Some(buddy));}
    let finley=hero_roots.iter().find(|h|h.hero_power==Some(cid("TB_BaconShop_HP_057"))).expect("Finley remains in original hero pool").cid;
    let (seed,mut g,n)=(0..1024).find_map(|seed| {
        let g=Game::new(seed,RulesConfig{num_players:2,..RulesConfig::default()});
        let Some(Pending::HeroSelect{options})=g.players[0].pending.last() else {return None};
        options.iter().position(|c|*c==finley).map(|n|(seed,g,n))
    }).expect("unmodified natural hero offers contain Finley in bounded search");
    assert!(g.cfg.hero_pool.is_empty());assert!(g.cfg.hero_bans.is_empty());
    g.apply(0,Action::Choose(n)).unwrap();g.apply(1,Action::Choose(0)).unwrap();
    let all=taverngym::content::hero_power_pool(&g);
    assert!(!all.contains(&ambition));assert!(!all.contains(&conquest));
    // Buddy-pool implementation is private; its absent root is checked above.
    // Do not expose a production API solely for this evidence fixture.
    let Some(Pending::HeroPowerChoice{options,slot})=g.players[0].pending.last() else {panic!("real Finley discovery menu")};
    assert_eq!(*slot,0);assert_eq!(options.len(),3);assert!(options.iter().all(|c|all.contains(c)));let selected=options[0];
    println!("natural Finley seed={seed}; full hero metadata roots={}; lobby power candidates={}; menu={:?}",hero_roots.len(),all.len(),options.iter().map(|c|&db().get(*c).id).collect::<Vec<_>>());
    g.apply(0,Action::Choose(0)).unwrap();assert_eq!(g.players[0].hero_power(),Some(selected));
}
