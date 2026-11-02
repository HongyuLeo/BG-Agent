mod common;
use common::*;
use taverngym::debug::{DebugCmd,run_debug};

fn raw(g:&Game)->String{serde_json::to_string(g).unwrap()}
fn dump(name:&str,g:&Game){if let Ok(p)=std::env::var("EVIDENCE_DIR"){std::fs::create_dir_all(&p).unwrap();std::fs::write(std::path::Path::new(&p).join(format!("{name}.json")),raw(g)).unwrap();}}
fn trinket(g:&mut Game,id:&str){run_debug(g,DebugCmd::GiveTrinket{p:0,card:id.into()}).unwrap();g.players[0].pending.clear();}
fn stitch(g:&mut Game,eid:u32){let hand=g.players[0].hand.iter().position(|h|h.item.card()==cid("BG35_MagicItem_838t")).unwrap();g.apply(0,Action::Play{hand,pos:0}).unwrap();let Some(Pending::Target{options,..})=g.players[0].pending.last() else{panic!("real838t must offer an exact friendly target")};assert!(options.contains(&eid));let i=options.iter().position(|x|*x==eid).unwrap();g.apply(0,Action::Choose(i)).unwrap();}

#[test]
fn base_coil_public_magnetize_keeps_300_and_300t_levels_separate(){
 let mut g=game(901);trinket(&mut g,"BG35_MagicItem_300");trinket(&mut g,"BG35_MagicItem_300t");set_board(&mut g,0,&["BG26_147"]);let base=g.players[0].board[0].atk;
 dump("coil_before",&g);
 for _ in 0..2{give(&mut g,0,"BG34_Giant_610t");let hand=g.players[0].hand.len()-1;g.apply(0,Action::Magnetize{hand,board:0}).unwrap();}
 dump("coil_after",&g);assert_eq!(g.players[0].board[0].atk,base+8+1+2+2+4,"base1/2 and greater2/4 must both react with distinct identity levels");
}
#[test]
fn greater_coil_neighbor_control_unchanged(){let mut g=game(902);trinket(&mut g,"BG35_MagicItem_300t");set_board(&mut g,0,&["BG26_147"]);let base=g.players[0].board[0].atk;for _ in 0..2{give(&mut g,0,"BG34_Giant_610t");let hand=g.players[0].hand.len()-1;g.apply(0,Action::Magnetize{hand,board:0}).unwrap();}assert_eq!(g.players[0].board[0].atk,base+8+2+4);}
#[test]
fn needle_grants_exact_temporary_spellcraft(){let mut g=game(903);trinket(&mut g,"BG35_MagicItem_838");dump("needle_grant",&g);let h=g.players[0].hand.iter().find(|h|h.item.card()==cid("BG35_MagicItem_838t")).expect("Needle must grant exact838t on attach");assert!(h.temporary);assert_eq!(h.src,0);}
#[test]
fn needle_exact_entity_locked_no_triple_and_raw_restore(){
 let mut g=game(904);set_board(&mut g,0,&["BG26_147","BGS_115"]);let eid=g.players[0].board[0].eid;g.players[0].board[0].set_stats(7,9);g.players[0].board[0].give(Kw::DIVINE_SHIELD);let attached=cid("BG31_171t");g.players[0].board[0].attached.push(attached);give(&mut g,0,"BG26_147");give(&mut g,0,"BG26_147");give(&mut g,0,"BG35_MagicItem_838t");g.cfg.triple_copies=3;assert!(g.players[0].board.iter().any(|m|m.eid==eid));dump("needle_before_play",&g);
 let input=raw(&g);let mut restored:Game=serde_json::from_str(&input).unwrap();assert_eq!(raw(&restored),input);
 for x in [&mut g,&mut restored]{stitch(x,eid);assert!(!x.players[0].board.iter().any(|m|m.eid==eid));let h=x.players[0].hand.iter().find(|h|h.hid==eid).expect("same exact returned entity");assert_eq!(h.locked,1);let Item::Minion(m)=&h.item else{panic!()};assert_eq!((m.atk,m.hp,m.max_hp),(14,18,18));assert!(m.has(Kw::DIVINE_SHIELD));assert_eq!(m.attached,vec![attached]);assert_eq!(x.players[0].hand.iter().filter(|h|h.item.card()==cid("BG26_147")).count(),3,"locked third must not triple on arrival");let hand=x.players[0].hand.iter().position(|h|h.hid==eid).unwrap();assert!(x.apply(0,Action::Play{hand,pos:0}).is_err());}
 dump("needle_after_locked",&g);assert_eq!(raw(&g),raw(&restored));
}
#[test]
fn needle_fullhand_controlled_effect_cast_uses_existing_overflow(){
 let mut g=game(905);set_board(&mut g,0,&["BGS_115"]);let eid=g.players[0].board[0].eid;for _ in 0..g.cfg.hand_size{give(&mut g,0,"BG28_810");}dump("fullhand_before_effect",&g);g.with_recruit(0,|c|c.cast_spell(0,cid("BG35_MagicItem_838t"),0,eid,0));dump("fullhand_after",&g);
 assert_eq!(g.players[0].hand.len(),g.cfg.hand_size);assert!(g.players[0].hand.iter().all(|h|h.item.card()==cid("BG28_810")));assert!(!g.players[0].board.iter().any(|m|m.eid==eid));assert!(!g.players[0].hand.iter().any(|h|h.hid==eid));assert!(g.players[0].hand_queue.is_empty(),"ordinary838t does not gain new generic hand protection");
}
#[test]
fn needle_friendly_target_scope_rejects_other_owner(){let mut g=game(906);set_board(&mut g,0,&["BGS_115"]);set_board(&mut g,1,&["BGS_115"]);let own=g.players[0].board[0].eid;let other=g.players[1].board[0].eid;give(&mut g,0,"BG35_MagicItem_838t");let hand=g.players[0].hand.len()-1;g.apply(0,Action::Play{hand,pos:0}).unwrap();let Some(Pending::Target{options,..})=g.players[0].pending.last() else{panic!("targeted spell required")};assert!(options.contains(&own));assert!(!options.contains(&other));}
#[test]
fn needle_locked_hand_combat_boundary_and_next_own_turn_unlock(){
 let mut g=game(907);g.cfg.max_combat_attacks=1;set_board(&mut g,0,&["BG32_330","BG34_140"]);set_board(&mut g,1,&["BGS_115"]);g.players[1].board[0].set_stats(0,1000);let eid=g.players[0].board[0].eid;give(&mut g,0,"BG35_MagicItem_838t");stitch(&mut g,eid);let locked=raw(&g);let mut control=g.clone();control.players[0].hand.iter_mut().find(|h|h.hid==eid).unwrap().locked=0;let positive=fight(&mut control);let blocked=fight(&mut g);assert_eq!(blocked.stats[0].summons,0,"locked Scout cannot be summoned from hand");assert!(positive.stats[0].summons>0,"unlocked same Scout really triggers the existing combat hand mechanism");assert_eq!(g.players[0].hand.iter().find(|h|h.hid==eid).unwrap().locked,1);dump("locked_after_combat",&g);assert_eq!(g.players[0].board.len(),1);let mut clone:Game=serde_json::from_str(&locked).unwrap();end_turn_all(&mut clone);let h=clone.players[0].hand.iter().find(|h|h.hid==eid).expect("locked minion retained through real round");assert_eq!(h.locked,0);dump("unlocked_next_own_turn",&clone);
}
#[test]
fn needle_unused_token_expires_then_one_new_token_is_granted(){let mut g=game(908);g.cfg.max_combat_attacks=1;trinket(&mut g,"BG35_MagicItem_838");let old=g.players[0].hand.iter().find(|h|h.item.card()==cid("BG35_MagicItem_838t")).expect("initial token").hid;end_turn_all(&mut g);let tokens:Vec<_>=g.players[0].hand.iter().filter(|h|h.item.card()==cid("BG35_MagicItem_838t")).collect();assert_eq!(tokens.len(),1);assert_ne!(tokens[0].hid,old);assert!(tokens[0].temporary);}
