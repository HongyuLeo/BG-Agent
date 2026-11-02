//! Explicit target offering contract. A source-qualified declaration is not source authentication.
use serde::{Deserialize,Serialize};
use crate::{cards::db,script::{implemented,script},config::{RulesConfig,ContentMode}};
#[derive(Clone,Debug,Serialize,Deserialize)]
#[serde(deny_unknown_fields)]
pub struct DirectOffers {pub minion:Vec<String>,pub tavern_spell:Vec<String>,pub hero:Vec<String>,pub trinket:Vec<String>}
#[derive(Clone,Debug,Serialize,Deserialize)]
#[serde(deny_unknown_fields)]
pub struct DerivedParent {pub parent:String,pub child:String}
#[derive(Clone,Debug,Serialize,Deserialize)]
#[serde(deny_unknown_fields)]
pub struct DeniedGiftPair {pub minion:String,pub gift:String}
#[derive(Clone,Debug,Serialize,Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ExecutionIdentityBinding {pub source_parent:String,pub source_power:String,pub source_child_id:String,pub source_child_dbf:u32,pub execution_child_id:String,pub execution_child_dbf:u32,pub decision_sha256:String,pub evidence_sha256:String}
#[derive(Clone,Debug,Serialize,Deserialize)]
#[serde(deny_unknown_fields)]
pub struct TargetManifest {
 pub ruleset_id:String,pub target_build:String,pub source_qualified:bool,
 pub public_offer:DirectOffers,pub supported_derived:Vec<String>,pub excluded:Vec<String>,pub source_unknown:Vec<String>,pub derived_parents:Vec<DerivedParent>,pub denied_gift_pairs:Vec<DeniedGiftPair>,pub execution_identity_bindings:Vec<ExecutionIdentityBinding>,
}
#[derive(Clone,Debug,Serialize,Deserialize)]
#[serde(deny_unknown_fields)]
pub struct TargetRoster {pub manifest_sha256:String,pub manifest:TargetManifest}
impl TargetRoster {
 pub fn direct(&self,kind:&str,id:&str)->bool {let p=&self.manifest.public_offer;let ids=match kind {"minion"=>&p.minion,"tavern_spell"=>&p.tavern_spell,"hero"=>&p.hero,"trinket"=>&p.trinket,_=>return false};ids.iter().any(|x|x==id)}
 /// Query the declared parent route only. This does not rewrite historical copy/transform callbacks.
 pub fn parent_route_allowed(&self,parent:&str,child:&str)->bool {
  !self.manifest.excluded.iter().chain(self.manifest.source_unknown.iter()).any(|id|id==parent)
   && self.manifest.supported_derived.iter().any(|id|id==child)
   && self.manifest.derived_parents.iter().any(|r|r.parent==parent&&r.child==child)
 }
 pub fn digest(&self)->String {
  // serde_json::Value uses sorted object keys; array order and UTF-8 strings are retained.
  let bytes=serde_json::to_vec(&serde_json::to_value(&self.manifest).unwrap()).unwrap();sha256(&bytes)
 }
 pub fn validate(&self,cfg:&RulesConfig)->Result<(),String> {
  let fail=|why:&str|Err(format!("target_roster: {why}"));
  if self.manifest.ruleset_id.trim().is_empty()||self.manifest.target_build.trim().is_empty(){return fail("named ruleset/build required")}
  if !self.manifest.source_qualified{return fail("source-qualified declaration required (not authentication)")}
  if self.manifest_sha256!=self.digest(){return fail("manifest SHA256 mismatch")}
  if cfg.content!=ContentMode::Implemented||!cfg.hero_pool.is_empty()||cfg.experimental_mode{return fail("Implemented content, no experimental mode or hero_pool override required")}
  let m=&self.manifest;let d=db();let mut seen=std::collections::HashSet::new();
  for ids in [&m.public_offer.minion,&m.public_offer.tavern_spell,&m.public_offer.hero,&m.public_offer.trinket,&m.supported_derived,&m.excluded,&m.source_unknown] {
   for id in ids {if !seen.insert(id){return fail("duplicate or overlapping identity")};if id.is_empty() || !id.bytes().all(|b| b.is_ascii_alphanumeric() || b == b'_') {return fail("invalid identity syntax")}
    if d.find(id).is_none() && !m.source_unknown.contains(id) {
     let parents:Vec<_>=m.derived_parents.iter().filter(|link| &link.child==id).collect();
     let inactive=m.supported_derived.contains(id)&&!parents.is_empty()&&parents.iter().all(|link|m.excluded.contains(&link.parent)||m.source_unknown.contains(&link.parent));
     if !inactive{return fail(&format!("unknown active identity {id}"))}
    }}
  }
  for (kind,ids) in [("minion",&m.public_offer.minion),("tavern_spell",&m.public_offer.tavern_spell),("hero",&m.public_offer.hero),("trinket",&m.public_offer.trinket)] {
   for id in ids {let c=d.get(d.id(id));
    if c.normal.is_some(){return fail(&format!("derived/golden identity cannot be direct: {id}"))}
    let ok=match kind {"minion"=>c.kind==crate::cards::CardKind::Minion&&c.tier>=1&&c.tier<=7&&implemented(c.cid),"tavern_spell"=>c.kind==crate::cards::CardKind::TavernSpell&&c.tier>=1&&c.tier<=7&&implemented(c.cid)&&script(c.cid).is_some(),"hero"=>c.kind==crate::cards::CardKind::Hero&&c.hero_power.is_some_and(|p|script(p).is_some()),"trinket"=>c.kind.is_trinket()&&script(c.cid).is_some(),_=>false};
    if !ok{return fail(&format!("unsupported or wrong direct category: {id}"))}
   }
  }
  let mut links=std::collections::HashSet::new();
  for link in &m.derived_parents {
   if (d.find(&link.parent).is_none()&&!m.source_unknown.contains(&link.parent))||!m.supported_derived.contains(&link.child)||link.parent==link.child||!links.insert((&link.parent,&link.child)){return fail("invalid/duplicate or excluded/unknown parent route")}
  }
  let mut pairs=std::collections::HashSet::new();
  for pair in &m.denied_gift_pairs {
   if !d.find(&pair.minion).is_some_and(|id| d.get(id).kind==crate::cards::CardKind::Minion)||!d.find(&pair.gift).is_some_and(|id| d.get(id).kind==crate::cards::CardKind::DarkGift)||!pairs.insert((&pair.minion,&pair.gift)){return fail("unknown/wrong type/duplicate exact gift pair")}
  }
  for binding in &m.execution_identity_bindings {
   let hex=|s:&str|s.len()==64&&s.bytes().all(|b|b.is_ascii_digit()||(b'a'..=b'f').contains(&b));
   let parent=d.find(&binding.source_parent);let power=d.find(&binding.source_power);let child=d.find(&binding.execution_child_id);
   if !hex(&binding.decision_sha256)||!hex(&binding.evidence_sha256)||binding.source_child_id.is_empty()||binding.source_child_dbf==0||!parent.is_some_and(|id|d.get(id).kind==crate::cards::CardKind::Hero&&d.get(id).hero_power==power)||!power.is_some_and(|id|d.get(id).kind==crate::cards::CardKind::HeroPower)||!child.is_some_and(|id|d.get(id).dbf==binding.execution_child_dbf)||!m.supported_derived.contains(&binding.execution_child_id){return fail("invalid version identity provenance")}
  }
  // This is an offering boundary and an explicit dependency record, not a universal
  // runtime ban on old transform/copy callbacks. Derivation does not add a pool member.
  Ok(())
 }
}
// SHA-256 without adding a toolchain dependency. Used only for configuration validation.
fn sha256(input:&[u8])->String {
 const K:[u32;64]=[0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2];
 let mut bytes=input.to_vec();let bits=(bytes.len() as u64)*8;bytes.push(0x80);while bytes.len()%64!=56{bytes.push(0)}bytes.extend_from_slice(&bits.to_be_bytes());
 let mut h:[u32;8]=[0x6a09e667,0xbb67ae85,0x3c6ef372,0xa54ff53a,0x510e527f,0x9b05688c,0x1f83d9ab,0x5be0cd19];
 for chunk in bytes.chunks_exact(64){let mut w=[0u32;64];for (i,c) in chunk.chunks_exact(4).enumerate(){w[i]=u32::from_be_bytes(c.try_into().unwrap())}for i in 16..64{let s0=w[i-15].rotate_right(7)^w[i-15].rotate_right(18)^(w[i-15]>>3);let s1=w[i-2].rotate_right(17)^w[i-2].rotate_right(19)^(w[i-2]>>10);w[i]=w[i-16].wrapping_add(s0).wrapping_add(w[i-7]).wrapping_add(s1)}
 let [mut a,mut b,mut c,mut d,mut e,mut f,mut g,mut x]=h;
 for i in 0..64{let s1=e.rotate_right(6)^e.rotate_right(11)^e.rotate_right(25);let ch=(e&f)^(!e&g);let t1=x.wrapping_add(s1).wrapping_add(ch).wrapping_add(K[i]).wrapping_add(w[i]);let s0=a.rotate_right(2)^a.rotate_right(13)^a.rotate_right(22);let maj=(a&b)^(a&c)^(b&c);let t2=s0.wrapping_add(maj);x=g;g=f;f=e;e=d.wrapping_add(t1);d=c;c=b;b=a;a=t1.wrapping_add(t2)}
 for (v,n) in h.iter_mut().zip([a,b,c,d,e,f,g,x]){*v=v.wrapping_add(n)}
 }h.iter().map(|n|format!("{n:08x}")).collect()
}
#[cfg(test)] mod tests {#[test]fn sha_known_vectors(){assert_eq!(super::sha256(b""),"e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855");assert_eq!(super::sha256(b"abc"),"ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad");}}

#[cfg(test)] mod legacy_tests {
 #[test] fn none_full_raw_matches_frozen_native_seed97() {
  let raw=serde_json::to_string(&crate::Game::new(97,crate::RulesConfig::default())).unwrap();
  assert_eq!(super::sha256(raw.as_bytes()),include_str!("../tests/fixtures/legacy_raw_seed97.sha256").trim());
 }
}
