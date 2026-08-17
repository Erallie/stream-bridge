from __future__ import annotations
import hashlib, json, sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

def now() -> str: return datetime.now(timezone.utc).isoformat()

@dataclass(frozen=True)
class GuildConfig:
    guild_id: str
    channel_ids: tuple[str, ...]
    session_id: str | None
    relay_targets: tuple[str, ...]
    discord_relay_channel_id: str | None = None

class ConfigStore:
    def __init__(self, path: str) -> None:
        p=Path(path); p.parent.mkdir(parents=True,exist_ok=True)
        self.connection=sqlite3.connect(p); self.connection.row_factory=sqlite3.Row
        self.connection.execute("PRAGMA journal_mode=WAL"); self.connection.execute("PRAGMA foreign_keys=ON")
        self.connection.executescript("""
        CREATE TABLE IF NOT EXISTS guild_config(guild_id TEXT PRIMARY KEY,channel_id TEXT,ssn_session_id TEXT,relay_targets TEXT NOT NULL DEFAULT '',updated_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS guild_channels(guild_id TEXT NOT NULL,channel_id TEXT NOT NULL,created_at TEXT NOT NULL,PRIMARY KEY(guild_id,channel_id));
        INSERT OR IGNORE INTO guild_channels SELECT guild_id,channel_id,updated_at FROM guild_config WHERE channel_id IS NOT NULL;
        CREATE TABLE IF NOT EXISTS guild_settings(guild_id TEXT NOT NULL,key TEXT NOT NULL,value TEXT NOT NULL,PRIMARY KEY(guild_id,key));
        CREATE TABLE IF NOT EXISTS processed_events(guild_id TEXT NOT NULL,event_key TEXT NOT NULL,platform TEXT NOT NULL,message_id TEXT NOT NULL DEFAULT '',fingerprint TEXT NOT NULL,created_at TEXT NOT NULL,PRIMARY KEY(guild_id,event_key));
        CREATE TABLE IF NOT EXISTS deliveries(guild_id TEXT NOT NULL,event_key TEXT NOT NULL,destination TEXT NOT NULL,status TEXT NOT NULL,created_at TEXT NOT NULL,PRIMARY KEY(guild_id,event_key,destination));
        """); self.connection.commit()
    def _ensure(self,g:str)->None:
        self.connection.execute("INSERT OR IGNORE INTO guild_config VALUES(?,NULL,NULL,'',?)",(g,now()))
    def get(self,g:str)->GuildConfig|None:
        r=self.connection.execute("SELECT * FROM guild_config WHERE guild_id=?",(g,)).fetchone()
        if not r:return None
        cs=tuple(x[0] for x in self.connection.execute("SELECT channel_id FROM guild_channels WHERE guild_id=? ORDER BY created_at,channel_id",(g,)))
        return GuildConfig(g,cs,r['ssn_session_id'],tuple(filter(None,r['relay_targets'].split(','))),self.get_setting(g,'discord_relay_channel_id'))
    def configured_guilds(self)->list[GuildConfig]:
        return [c for r in self.connection.execute("SELECT guild_id FROM guild_config WHERE ssn_session_id IS NOT NULL") if (c:=self.get(r[0]))]
    def set_session(self,g:str,s:str,targets:list[str])->None:
        self._ensure(g); self.connection.execute("UPDATE guild_config SET ssn_session_id=?,relay_targets=?,updated_at=? WHERE guild_id=?",(s,','.join(targets),now(),g)); self.connection.commit()
    def clear_session(self,g:str)->None:self.connection.execute("UPDATE guild_config SET ssn_session_id=NULL,relay_targets='',updated_at=? WHERE guild_id=?",(now(),g));self.connection.commit()
    def add_channel(self,g:str,c:str)->bool:
        self._ensure(g);x=self.connection.execute("INSERT OR IGNORE INTO guild_channels VALUES(?,?,?)",(g,c,now()));self.connection.commit();return x.rowcount>0
    def remove_channel(self,g:str,c:str)->bool:
        x=self.connection.execute("DELETE FROM guild_channels WHERE guild_id=? AND channel_id=?",(g,c));self.connection.commit();return x.rowcount>0
    def clear_channels(self,g:str)->int:
        x=self.connection.execute("DELETE FROM guild_channels WHERE guild_id=?",(g,));self.connection.commit();return x.rowcount
    def set_setting(self,g:str,k:str,v:Any)->None:
        self._ensure(g);self.connection.execute("INSERT INTO guild_settings VALUES(?,?,?) ON CONFLICT(guild_id,key) DO UPDATE SET value=excluded.value",(g,k,json.dumps(v)));self.connection.commit()
    def get_setting(self,g:str,k:str,d:Any=None)->Any:
        r=self.connection.execute("SELECT value FROM guild_settings WHERE guild_id=? AND key=?",(g,k)).fetchone();return json.loads(r[0]) if r else d
    @staticmethod
    def event_key(p:str,mid:str,uid:str,text:str,ts:int|str)->tuple[str,str]:
        norm=' '.join(text.casefold().split());fp=hashlib.sha256(f'{p}|{uid}|{norm}'.encode()).hexdigest();src=f'{p}|{mid}' if mid else f'{fp}|{str(ts)[:10]}';return hashlib.sha256(src.encode()).hexdigest(),fp
    def claim_event(self,g:str,p:str,mid:str,uid:str,text:str,ts:int|str)->str|None:
        key,fp=self.event_key(p,mid,uid,text,ts);x=self.connection.execute("INSERT OR IGNORE INTO processed_events VALUES(?,?,?,?,?,?)",(g,key,p,mid,fp,now()));self.connection.commit();return key if x.rowcount else None
    def claim_delivery(self,g:str,key:str,dest:str)->bool:
        x=self.connection.execute("INSERT OR IGNORE INTO deliveries VALUES(?,?,?,?,?)",(g,key,dest,'sent',now()));self.connection.commit();return x.rowcount>0
    def close(self)->None:self.connection.close()
