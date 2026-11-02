//! Validate a separately frozen external binding without creating a game or changing a pool.
fn main() {
 let path=std::env::args().nth(1).expect("usage: target_roster_check <binding.json>");
 let binding:serde_json::Value=serde_json::from_str(&std::fs::read_to_string(path).unwrap()).unwrap();
 let cfg=serde_json::json!({"target_roster":binding});
 match taverngym::RulesConfig::from_json(&cfg.to_string()) {
  Ok(c)=>println!("{}",serde_json::json!({"accepted":true,"ruleset_id":c.target_roster.as_ref().unwrap().manifest.ruleset_id,"game_created":false})),
  Err(e)=>{println!("{}",serde_json::json!({"accepted":false,"reason":e,"game_created":false}));std::process::exit(1)}
 }
}
