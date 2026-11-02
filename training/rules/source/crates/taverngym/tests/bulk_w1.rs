use taverngym::{Game,RulesConfig};
use taverngym::actions::Action;
use taverngym::cards::cid;
use taverngym::engine::Ctx;
use taverngym::script::script;
use taverngym::state::{Minion,Pending,Item,ShopSlot};
fn game()->Game { let mut g=Game::new(541,RulesConfig{num_players:2,record_log:true,..Default::default()});for p in 0..2 {g.apply(p,Action::Choose(0)).unwrap();} for p in &mut g.players {p.pending.clear();p.hand.clear();p.board.clear();p.shop.clear();p.powers.clear();p.effects.clear();p.quests.clear();p.trinkets.clear();p.counters.clear();p.stats=Default::default();p.gold=10;p.tier=6;p.skipping=false;}g.next_eid=200;g }
fn body(e:u32,id:&str)->Minion {let mut m=Minion::new(e,cid(id));m.set_stats(10,10);m}
fn give(g:&mut Game,id:&str){g.with_recruit(0,|c|{c.give_card(0,cid(id));});}
fn target(g:&mut Game,e:u32){let options=match g.players[0].pending.last().unwrap(){Pending::Target{options,..}=>options,_=>panic!()};let i=options.iter().position(|x|*x==e).unwrap();g.apply(0,Action::Choose(i)).unwrap();}
fn play(g:&mut Game,id:&str,e:u32){give(g,id);let h=g.players[0].hand.len()-1;g.apply(0,Action::Play{hand:h,pos:0}).unwrap();if !g.players[0].pending.is_empty(){target(g,e);}}
fn raw(g:&Game)->String{serde_json::to_string(g).unwrap()}
#[test]fn w1_callbacks(){for id in ["BG23_002","BG23_002_G"]{assert!(script(cid(id)).and_then(|s|s.battlecry).is_some(),"{id}");}for id in ["BG26_505","BG26_505_G","BG36_622","BG36_622_G","BG36_921","BG36_921_G"]{assert!(script(cid(id)).and_then(|s|s.on_event).is_some(),"{id}");}}
#[test]fn w1_shell_normal_gold_coins_spend_once(){for (id,n) in [("BG23_002",1),("BG23_002_G",2)]{let mut g=game();play(&mut g,id,0);assert_eq!(g.players[0].hand.iter().filter(|h|h.item.card()==cid("BG28_810")).count(),n);assert_eq!(g.players[0].hand.len(),n+usize::from(id.ends_with("_G")));g.players[0].gold=0;for _ in 0..n {let h=g.players[0].hand.iter().position(|h|h.item.card()==cid("BG28_810")).unwrap();g.apply(0,Action::Play{hand:h,pos:0}).unwrap();}assert_eq!(g.players[0].gold,n as i32);}}
#[test]fn w1_fugitive_stack_and_target_side_filters(){for (id,k) in [("BG36_921",1),("BG36_921_G",2)]{let mut g=game();let mut c=Ctx::new(&mut g,[vec![body(101,id),body(102,"BGS_115")],vec![body(103,id)]],[Some(0),Some(1)],false);c.you_cast(0,cid("BG23_000t"),0,101,0);c.you_cast(0,cid("BG23_000t"),0,101,0);c.you_cast(0,cid("BG23_000t"),0,102,0);c.you_cast(1,cid("BG23_000t"),0,101,0);assert_eq!(c.minion(101).unwrap().max_hp,10+2*k);assert_eq!(c.minion(103).unwrap().max_hp,10);}}
#[test]fn w1_ruiner_naga_all_tavern_and_owner(){for (id,k) in [("BG36_622",1),("BG36_622_G",2)]{for naga in ["BG23_004","BG25_039","BG24_017"]{let mut g=game();g.players[0].shop.push(ShopSlot::new(104,Item::Minion(body(104,naga))));let mut c=Ctx::new(&mut g,[vec![body(101,id),body(102,"BGS_115")],vec![body(103,naga)]],[Some(0),Some(1)],false);c.you_cast(0,cid("BG23_000t"),0,104,0);assert_eq!(c.minion(101).unwrap().max_hp,10+3*k);assert_eq!(c.minion(102).unwrap().max_hp,10+3*k);c.you_cast(0,cid("BG23_000t"),0,102,0);c.you_cast(1,cid("BG23_000t"),0,103,0);assert_eq!(c.minion(101).unwrap().max_hp,10+3*k);}}}
#[test]fn w1_shaker_only_hand_spellcraft_once_copies_source_and_turn_reset(){for (id,n) in [("BG26_505",1),("BG26_505_G",2)]{let mut g=game();g.players[0].board.push(body(101,id));g.players[0].board.push(body(102,"BG23_004"));play(&mut g,"BG23_000t",102);assert!(g.players[0].hand.is_empty());play(&mut g,"BG28_810",0);assert!(g.players[0].hand.is_empty());g.with_recruit(0,|c|{c.you_cast(0,cid("BG23_000t"),0,101,0);});assert!(g.players[0].hand.is_empty());g.with_recruit(0,|c|{c.give_temp_spell(0,cid("BG23_000t"),102);});g.apply(0,Action::Play{hand:0,pos:0}).unwrap();target(&mut g,101);assert_eq!(g.players[0].hand.len(),n);assert!(g.players[0].hand.iter().all(|h|h.temporary && h.src==102 && h.item.card()==cid("BG23_000t")));g.apply(0,Action::Play{hand:0,pos:0}).unwrap();target(&mut g,101);assert_eq!(g.players[0].hand.len(),n-1);let m=&mut g.players[0].board[0];let me=taverngym::script::Me{side:0,eid:101,card:m.card,golden:m.golden,opt:0,pos:0,data:0};g.with_recruit(0,|c|{script(me.card).unwrap().start_of_turn.unwrap()(c,me);});play(&mut g,"BG23_000t",101);assert_eq!(g.players[0].hand.len(),2*n-1);}}
#[test]fn w1_public_pending_clone_restore_exact(){for id in ["BG26_505","BG26_505_G","BG36_622","BG36_622_G","BG36_921","BG36_921_G"]{let mut g=game();g.players[0].board.push(body(101,id));give(&mut g,"BG23_000t");g.apply(0,Action::Play{hand:0,pos:0}).unwrap();let saved=raw(&g);let mut h:Game=serde_json::from_str(&saved).unwrap();let mut k=g.clone();assert!(g.apply(0,Action::Choose(99)).is_err());assert_eq!(saved,raw(&g));for b in [&mut g,&mut h,&mut k]{target(b,101);}assert_eq!(raw(&g),raw(&h));assert_eq!(raw(&g),raw(&k));}}

#[test]
fn w1_shaker_capacity_expiry_source_departure_and_used_state_restore() {
    for id in ["BG26_505", "BG26_505_G"] {
        let mut g=game();g.players[0].board.push(body(101,id));
        // A full hand has exactly one slot opened by playing the spell.
        give(&mut g,"BG23_000t");for _ in 1..g.cfg.hand_size {give(&mut g,"BG28_810");}
        g.apply(0,Action::Play{hand:0,pos:0}).unwrap();target(&mut g,101);
        assert_eq!(g.players[0].hand.len(),g.cfg.hand_size);
        assert!(g.players[0].hand_queue.is_empty());
        assert_eq!(g.players[0].hand.iter().filter(|h|h.temporary).count(),1);
        let prefix=raw(&g);let mut restored:Game=serde_json::from_str(&prefix).unwrap();
        for branch in [&mut g,&mut restored] {
            let h=branch.players[0].hand.iter().position(|h|h.temporary).unwrap();
            branch.apply(0,Action::Play{hand:h,pos:0}).unwrap();target(branch,101);
            assert!(branch.players[0].hand.iter().all(|h|!h.temporary));
        }
        assert_eq!(raw(&g),raw(&restored));
        // Selling removes the listener; another target cannot create another copy.
        g.apply(0,Action::Sell(0)).unwrap();g.players[0].board.push(body(102,"BG23_004"));
        let before=g.players[0].hand.len();play(&mut g,"BG23_000t",102);assert_eq!(g.players[0].hand.len(),before);
        let mut expiry=game();expiry.players[0].board.push(body(101,id));play(&mut expiry,"BG23_000t",101);
        assert!(expiry.players[0].hand.iter().all(|h|h.temporary));
        expiry.apply(0,Action::EndTurn).unwrap();assert!(expiry.players[0].hand.is_empty());
    }
}
#[test]
fn w1_shell_overflow_obeys_existing_hand_contract() {
    for id in ["BG23_002","BG23_002_G"] {
        let mut g=game();give(&mut g,id);for _ in 1..g.cfg.hand_size {give(&mut g,"BG28_810");}
        g.apply(0,Action::Play{hand:0,pos:0}).unwrap();assert_eq!(g.players[0].hand.len(),g.cfg.hand_size);
        assert!(g.players[0].hand_queue.is_empty());
    }
}
