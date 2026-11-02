//! Capture privileged raw state for same-effect-set before/after optional-entry comparison.
fn main(){let mut args=std::env::args().skip(1);let seed:u64=args.next().expect("seed").parse().unwrap();let output=args.next().expect("output file");let g=taverngym::Game::new(seed,taverngym::RulesConfig::default());let raw=serde_json::to_string(&g).unwrap();std::fs::write(output,raw).unwrap();}
