//! Controlled native-state contracts; these fixtures do not establish fresh Azshara draftability.
use taverngym::{Action, Game, RulesConfig};
use taverngym::cards::{cid, db};
use taverngym::state::{Item, Pending};
use taverngym::types::{EntityId, Kw, Races};

fn game() -> Game {
    let mut g=Game::new(977,RulesConfig{num_players:2,triple_copies:99,lesser_trinket_turn:0,greater_trinket_turn:0,..RulesConfig::default()});
    for p in 0..2 {g.apply(p,Action::Choose(0)).unwrap();}
    for p in &mut g.players {p.pending.clear();p.hand.clear();p.board.clear();p.shop.clear();p.trinkets.clear();p.effects.clear();p.quests.clear();p.powers.clear();p.gold=30;p.skipping=false;p.stats=Default::default();}
    g
}
fn body(g:&mut Game,id:&str)->EntityId {
    let m=g.with_recruit(0,|c| c.new_minion(0,cid(id)));let e=m.eid;g.players[0].board.push(m);e
}
fn raw(g:&Game)->String {serde_json::to_string(g).unwrap()}
fn stats(g:&Game,e:EntityId)->(i32,i32) {let m=g.players[0].board.iter().find(|m|m.eid==e).unwrap();(m.atk,m.hp)}
fn cast(g:&mut Game,id:&str,data:i32,opt:usize,target:Option<EntityId>) {
    g.with_recruit(0,|c| {c.add_to_hand(0,Item::Spell{card:cid(id),data});});
    let hand=g.players[0].hand.len()-1;g.apply(0,Action::Play{hand,pos:0}).unwrap();
    if matches!(g.players[0].pending.last(),Some(Pending::ChooseOne{..})){g.apply(0,Action::Choose(opt)).unwrap();}
    if let Some(target)=target {
        let Some(Pending::Target{options,..})=g.players[0].pending.last() else {panic!("target menu for {id}")};
        let n=options.iter().position(|e|*e==target).expect("real target menu contains target");g.apply(0,Action::Choose(n)).unwrap();
    }
    assert!(g.players[0].pending.is_empty());
}
fn acquire(g:&mut Game,golden:bool)->EntityId {
    if g.players[0].powers.is_empty() {g.with_recruit(0,|c| c.set_hero_power(0,0,cid("BG22_HERO_007p2")));}
    let id=if golden{"BG35_MagicItem_803t"}else{"BG35_MagicItem_803"};
    g.players[0].pending.push(Pending::Trinket{options:vec![cid(id)],free:false,replace:None});
    g.apply(0,Action::Choose(0)).unwrap();
    let hand=g.players[0].hand.len()-1;
    let expected=db().get(cid("BG22_HERO_007_Buddy")).golden.filter(|_|golden).unwrap_or(cid("BG22_HERO_007_Buddy"));
    assert_eq!(g.players[0].hand[hand].item.card(),expected);
    g.apply(0,Action::Play{hand,pos:g.players[0].board.len()}).unwrap();
    g.players[0].board.last().unwrap().eid
}

#[test]fn purchase_play_recast_once_and_reset_next_turn() {
    for golden in [false,true] {
        let mut g=game();let target=body(&mut g,"BG23_002");let buddy=acquire(&mut g,golden);let base=stats(&g,buddy);let n=if golden{2}else{1};
        cast(&mut g,"BG20_GEM",0,0,Some(target));assert_eq!(stats(&g,buddy),(base.0+n,base.1+n));assert_eq!(g.players[0].stats.spells_cast,1+n);
        cast(&mut g,"BG20_GEM",0,0,Some(target));assert_eq!(stats(&g,buddy),(base.0+n,base.1+n));
        let before=stats(&g,buddy);g.start_turn();assert!(g.players[0].pending.is_empty());
        cast(&mut g,"BG20_GEM",0,0,Some(target));assert_eq!(stats(&g,buddy),(before.0+n,before.1+n));
    }
}
#[test]fn self_untargeted_and_tavern_casts_do_not_spend_the_use() {
    let mut g=game();let target=body(&mut g,"BG23_002");let buddy=acquire(&mut g,false);
    cast(&mut g,"BG20_GEM",0,0,Some(buddy));let base=stats(&g,buddy);
    cast(&mut g,"BG28_810",0,0,None);
    let m=g.with_recruit(0,|c| c.new_minion(0,cid("BG23_002")));let sid=m.eid;g.players[0].shop.push(taverngym::state::ShopSlot::new(sid,Item::Minion(m)));
    cast(&mut g,"BG36_624",0,0,Some(sid));assert_eq!(stats(&g,buddy),base);
    cast(&mut g,"BG20_GEM",0,0,Some(target));assert_eq!(stats(&g,buddy),(base.0+1,base.1+1));
}
#[test]fn choose_one_and_spell_data_are_preserved() {
    for golden in [false,true] {
        let mut g=game();let target=body(&mut g,"BG23_002");let buddy=acquire(&mut g,golden);let b=stats(&g,buddy);let n=if golden{2}else{1};
        cast(&mut g,"BG31_880",0,1,Some(target));assert_eq!(stats(&g,buddy),(b.0+n,b.1+3*n));
        g.start_turn();g.players[0].board.iter_mut().find(|m|m.eid==buddy).unwrap().races=Races::NAGA.union(Races::QUILBOAR);
        cast(&mut g,"BG20_GEM",2,0,Some(target));assert!(g.players[0].board.iter().find(|m|m.eid==buddy).unwrap().kw.has(Kw::DIVINE_SHIELD));
    }
}
#[test]fn two_buddies_reenter_safely_and_spend_each_entity_once() {
    for golden in [false,true] {
        let mut g=game();let target=body(&mut g,"BG23_002");let a=acquire(&mut g,golden);let b=acquire(&mut g,golden);let sa=stats(&g,a);let sb=stats(&g,b);let n=if golden{2}else{1};
        cast(&mut g,"BG20_GEM",0,0,Some(target));assert_eq!(stats(&g,a),(sa.0+n,sa.1+n));assert_eq!(stats(&g,b),(sb.0+n,sb.1+n));assert_eq!(g.players[0].stats.spells_cast,1+2*n);
        cast(&mut g,"BG20_GEM",0,0,Some(target));assert_eq!(stats(&g,a),(sa.0+n,sa.1+n));assert_eq!(stats(&g,b),(sb.0+n,sb.1+n));
    }
}
#[test]fn complete_raw_clone_restore_before_and_after_use_continue_identically() {
    for golden in [false,true] {for used in [false,true] {
        let mut g=game();let target=body(&mut g,"BG23_002");acquire(&mut g,golden);
        if used {cast(&mut g,"BG20_GEM",0,0,Some(target));}
        let original=raw(&g);let mut c=g.clone();let mut r:Game=serde_json::from_str(&original).unwrap();r.check_loaded().unwrap();assert_eq!(raw(&c),original);assert_eq!(raw(&r),original);
        for x in [&mut g,&mut c,&mut r] {cast(x,"BG31_880",0,1,Some(target));x.start_turn();cast(x,"BG20_GEM",0,0,Some(target));}
        assert_eq!(raw(&g),raw(&c));assert_eq!(raw(&g),raw(&r));
    }}
}
#[test]fn conditional_ambition_transform_preserves_other_hero_and_exact_buddy() {
    for golden in [false,true] {
        let mut g=game();let original_hero=g.players[0].hero;let target=body(&mut g,"BG23_002");g.players[0].board[0].atk=29;
        g.with_recruit(0,|c| c.set_hero_power(0,0,cid("BG22_HERO_007p")));
        assert_eq!(g.players[0].hero_power(),Some(cid("BG22_HERO_007p")));
        cast(&mut g,"BG20_GEM",0,0,Some(target));assert_eq!(g.players[0].hero_power(),Some(cid("BG22_HERO_007p2")));assert_eq!(g.players[0].hero,original_hero);
        acquire(&mut g,golden);
    }
}
