//! GPL-2.0-or-later. Separate, read-only Pro DJ Link helper for pi-dvs.
use rbl_index::{
    input::{library_from, TrackInput},
    Library, Playlists, NO_ID,
};
use rbl_link::Source;
use serde::Deserialize;
use serde_json::json;
use std::os::unix::fs::MetadataExt;
use std::{
    collections::{HashMap, HashSet},
    io::{self, BufRead, Write},
    path::{Path, PathBuf},
    sync::{mpsc, Arc},
    time::{Duration, Instant},
};

#[derive(Clone, Debug, PartialEq, Eq)]
struct Stamp {
    device: u64,
    inode: u64,
    size: u64,
    seconds: i64,
    nanos: i64,
    changed_seconds: i64,
    changed_nanos: i64,
}
impl Stamp {
    fn read(path: &Path) -> io::Result<Self> {
        let m = path.metadata()?;
        Ok(Self {
            device: m.dev(),
            inode: m.ino(),
            size: m.len(),
            seconds: m.mtime(),
            nanos: m.mtime_nsec(),
            changed_seconds: m.ctime(),
            changed_nanos: m.ctime_nsec(),
        })
    }
}
#[derive(Deserialize, Default)]
#[serde(default, deny_unknown_fields)]
struct Track {
    id: u32,
    title: String,
    artist: String,
    album: String,
    genre: String,
    key: String,
    path: String,
    analysis: String,
    artwork: String,
    duration: u32,
    bpm: u32,
    sample_rate: u32,
    bitrate: u32,
    bit_depth: u16,
    file_type: u8,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Playlist {
    id: u64,
    name: String,
    parent: Option<u64>,
    folder: bool,
    order: u32,
    tracks: Vec<u32>,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Catalog {
    generation: u32,
    root: PathBuf,
    database: PathBuf,
    tracks: Vec<Track>,
    playlists: Vec<Playlist>,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Command {
    revision: u64,
    catalog: Option<Catalog>,
}

struct Media {
    library: Arc<Library>,
    handle_base: u32,
    root: PathBuf,
    database: Option<(PathBuf, Stamp)>,
    root_identity: Option<(u64, u64)>,
    files: HashMap<PathBuf, Stamp>,
    assets: HashMap<PathBuf, Stamp>,
}
impl Media {
    fn empty() -> Self {
        Self {
            library: Arc::new(Library::default()),
            handle_base: 0,
            root: PathBuf::new(),
            database: None,
            root_identity: None,
            files: HashMap::new(),
            assets: HashMap::new(),
        }
    }
    fn current(&self) -> bool {
        let Some((db, expected)) = &self.database else {
            return true;
        };
        Stamp::read(db).is_ok_and(|s| s == *expected)
            && self
                .root
                .metadata()
                .is_ok_and(|m| Some((m.dev(), m.ino())) == self.root_identity)
    }
    fn load(mut catalog: Catalog) -> Result<Self, Box<dyn std::error::Error>> {
        if catalog.generation > 0x7fff_ffff
            || catalog.tracks.len() > 100_000
            || catalog.playlists.len() > 100_000
        {
            return Err("Export is too large".into());
        }
        let root = catalog.root.canonicalize()?;
        let database = catalog.database.canonicalize()?;
        if !database.starts_with(root.join("PIONEER/rekordbox")) {
            return Err("Database is outside selected export".into());
        }
        let db_stamp = Stamp::read(&database)?;
        let m = root.metadata()?;
        // FAT32 may resolve an export path with different capitalization. Store
        // its canonical spelling in both the catalog and the file allowlist.
        for track in &mut catalog.tracks {
            let path = Path::new(&track.path).canonicalize()?;
            if !path.starts_with(&root) || !path.is_file() {
                return Err("Track escapes selected USB".into());
            }
            track.path = path.to_str().ok_or("Non-UTF-8 audio path")?.to_owned();
        }
        let mut files = HashMap::new();
        let mut assets = HashMap::new();
        let mut records = Vec::new();
        let mut ids = HashSet::new();
        for t in &catalog.tracks {
            let path = Path::new(&t.path);
            if t.id == 0 || !ids.insert(t.id) {
                return Err("Duplicate or invalid track ID".into());
            }
            if !matches!(t.file_type, 1 | 4 | 11 | 12) {
                return Err("Unsupported CDJ-900 audio format".into());
            }
            if path.canonicalize()? != path || !path.starts_with(&root) || !path.is_file() {
                return Err("Track escapes selected USB".into());
            }
            let stamp = Stamp::read(path)?;
            if stamp.size == 0 {
                return Err("Empty audio file".into());
            }
            files.insert(path.to_owned(), stamp.clone());
            let mut candidates = Vec::new();
            if !t.analysis.is_empty() {
                let dat = root.join(t.analysis.trim_start_matches('/'));
                candidates.extend([
                    dat.clone(),
                    dat.with_extension("EXT"),
                    dat.with_extension("2EX"),
                ]);
            }
            if !t.artwork.is_empty() {
                let art = root.join(t.artwork.trim_start_matches('/'));
                candidates.push(art.clone());
                if let (Some(stem), Some(ext)) = (
                    art.file_stem().and_then(|s| s.to_str()),
                    art.extension().and_then(|s| s.to_str()),
                ) {
                    for suffix in ["_m", "_s"] {
                        candidates.push(art.with_file_name(format!("{stem}{suffix}.{ext}")));
                    }
                }
            }
            for candidate in candidates {
                if let Ok(path) = candidate.canonicalize() {
                    if path.starts_with(&root) && path.is_file() {
                        assets.insert(path.clone(), Stamp::read(&path)?);
                    }
                }
            }
            records.push(TrackInput {
                id: u64::from(t.id),
                title: &t.title,
                artist: &t.artist,
                album: &t.album,
                genre: &t.genre,
                key: &t.key,
                path: &t.path,
                length_sec: t.duration,
                bpm_x100: t.bpm,
                file_size: stamp.size,
                file_type: t.file_type,
                sample_rate: t.sample_rate,
                bitrate: t.bitrate,
                bit_depth: t.bit_depth,
                ..Default::default()
            });
        }
        let mut library = library_from(&records);
        library.analysis_path = Default::default();
        for t in &catalog.tracks {
            library.analysis_path.push(&t.analysis);
            library.artwork_path.push(&t.artwork);
        }
        let rows: HashMap<u32, u32> = catalog
            .tracks
            .iter()
            .enumerate()
            .map(|(i, t)| (t.id, i as u32))
            .collect();
        let parents: HashMap<u64, u32> = catalog
            .playlists
            .iter()
            .enumerate()
            .map(|(i, p)| (p.id, i as u32))
            .collect();
        let mut playlists = Playlists::default();
        for p in &catalog.playlists {
            playlists.ids.push(p.id);
            playlists.names.push(&p.name);
            playlists.parent.push(
                p.parent
                    .and_then(|id| parents.get(&id).copied())
                    .unwrap_or(NO_ID),
            );
            playlists.seq.push(p.order);
            playlists.attribute.push(u8::from(p.folder));
            playlists.smart.push("");
            playlists.members.push(
                p.tracks
                    .iter()
                    .filter_map(|id| rows.get(id).copied())
                    .collect(),
            );
        }
        library.set_playlists(playlists);
        let media = Self {
            library: Arc::new(library),
            handle_base: catalog.generation,
            root,
            database: Some((database, db_stamp)),
            root_identity: Some((m.dev(), m.ino())),
            files,
            assets,
        };
        if !media.current() {
            return Err("USB changed while preparing export".into());
        }
        Ok(media)
    }
}
/// Nominal-throughput policy, not a guarantee for WIDE/high-speed playback.
/// Keep the physically tested PCM16/44.1 kHz rate low without imposing that
/// same ceiling on higher-bitrate files. Unknown metadata keeps the old rate.
fn serving_read_rate(
    file_type: u8,
    sample_rate: u32,
    bit_depth: u16,
    bitrate: u32,
) -> std::num::NonZeroU64 {
    let nominal = match file_type {
        11 | 12
            if matches!(sample_rate, 32_000 | 44_100 | 48_000) && matches!(bit_depth, 16 | 24) =>
        {
            Some(u64::from(sample_rate) * u64::from(bit_depth) / 4)
        }
        1 | 4 if (8..=512).contains(&bitrate) => Some(u64::from(bitrate) * 125),
        _ => None,
    };
    let budget = nominal.map_or(512 * 1024, |bytes| {
        (bytes * 7).div_ceil(5).clamp(256 * 1024, 512 * 1024)
    });
    std::num::NonZeroU64::new(budget).unwrap()
}

impl Source for Media {
    fn read_asset(&self, path: &Path, limit: u64) -> Option<Vec<u8>> {
        use std::io::Read;
        if !self.current() {
            return None;
        }
        let path = path.canonicalize().ok()?;
        let expected = self.assets.get(&path)?;
        if !path.starts_with(&self.root)
            || expected.size > limit
            || Stamp::read(&path).ok()? != *expected
        {
            return None;
        }
        let mut bytes = Vec::new();
        std::fs::File::open(&path)
            .ok()?
            .take(limit + 1)
            .read_to_end(&mut bytes)
            .ok()?;
        if bytes.len() as u64 > limit || Stamp::read(&path).ok()? != *expected || !self.current() {
            return None;
        }
        Some(bytes)
    }
    fn library(&self) -> Option<Arc<Library>> {
        self.current().then(|| Arc::clone(&self.library))
    }
    fn share_root(&self) -> PathBuf {
        self.root.clone()
    }
    fn details(&self, _: &str) -> Option<rbl_db::details::TrackDetails> {
        None
    }
    fn file_exports(&self, _: &Library) -> rbl_nfs::Exports {
        let mut exports = rbl_nfs::Exports::with_id_base(self.handle_base).with_read_pacing();
        let mut tree = rbl_nfs::Vfs::new("/");
        let mut nodes = HashMap::new();
        for path in self.files.keys() {
            if let Some(name) = path.to_str() {
                let node = tree.add_file_unsized(name.trim_start_matches('/'), path);
                nodes.insert(path.as_path(), node);
            }
        }
        for row in 0..self.library.len() {
            let path = Path::new(self.library.folder_path.get(row));
            if let Some(&node) = nodes.get(path) {
                tree.set_read_rate(
                    node,
                    serving_read_rate(
                        self.library.file_type[row],
                        self.library.sample_rate[row],
                        self.library.bit_depth[row],
                        self.library.bitrate[row],
                    ),
                );
            }
        }
        let root = self.root.clone();
        let root_identity = self.root_identity;
        let database = self.database.clone();
        let files = self.files.clone();
        tree.set_guard(move |path| {
            let db_current = database
                .as_ref()
                .is_none_or(|(db, expected)| Stamp::read(db).is_ok_and(|s| s == *expected));
            db_current
                && root
                    .metadata()
                    .is_ok_and(|m| Some((m.dev(), m.ino())) == root_identity)
                && files
                    .get(path)
                    .is_some_and(|s| Stamp::read(path).is_ok_and(|now| now == *s))
                && path
                    .canonicalize()
                    .is_ok_and(|p| p == path && p.starts_with(&root))
        });
        exports.insert(tree);
        exports
    }
}
fn emit(value: serde_json::Value) -> io::Result<()> {
    let mut out = io::stdout().lock();
    serde_json::to_writer(&mut out, &value)?;
    writeln!(out)?;
    out.flush()
}
fn main() -> Result<(), Box<dyn std::error::Error>> {
    tracing_subscriber::fmt()
        .with_writer(io::stderr)
        .with_env_filter(tracing_subscriber::EnvFilter::from_default_env())
        .init();
    let args: Vec<String> = std::env::args().collect();
    if args.len() != 2 {
        return Err("usage: pi-dvs-link <wired-interface> (JSON commands on stdin)".into());
    }
    let interface = rbl_link::interfaces()
        .into_iter()
        .find(|i| i.name == args[1])
        .ok_or("Selected network interface is unavailable")?;
    let (tx, rx) = mpsc::sync_channel(1);
    std::thread::spawn(move || {
        let input = io::stdin();
        let mut input = input.lock();
        loop {
            let mut line = Vec::new();
            use std::io::Read;
            match input
                .by_ref()
                .take(32 * 1024 * 1024 + 1)
                .read_until(b'\n', &mut line)
            {
                Ok(0) | Err(_) => break,
                Ok(_) if line.len() > 32 * 1024 * 1024 => break,
                _ => {
                    if tx
                        .send(serde_json::from_slice::<Command>(&line).map_err(|e| e.to_string()))
                        .is_err()
                    {
                        break;
                    }
                }
            }
        }
    });
    let mut media = Arc::new(Media::empty());
    let mut link = Some(rbl_link::LinkExport::start(
        media.clone(),
        interface.clone(),
        rbl_link::Ports::REKORDBOX,
    )?);
    let mut revision = 0;
    let mut epoch = 0_u64;
    let mut error = String::new();
    let mut report_at = Instant::now();
    loop {
        match rx.recv_timeout(Duration::from_millis(100)) {
            Ok(Ok(command)) => {
                if let Some(old) = link.take() {
                    old.stop();
                }
                revision = command.revision;
                epoch += 1;
                media = match command.catalog.map(Media::load).transpose() {
                    Ok(value) => {
                        error.clear();
                        Arc::new(value.unwrap_or_else(Media::empty))
                    }
                    Err(failure) => {
                        error = failure.to_string();
                        Arc::new(Media::empty())
                    }
                };
                link = Some(rbl_link::LinkExport::start(
                    media.clone(),
                    interface.clone(),
                    rbl_link::Ports::REKORDBOX,
                )?);
            }
            Ok(Err(failure)) => {
                error = format!("Invalid catalog command: {failure}");
            }
            Err(mpsc::RecvTimeoutError::Disconnected) => break,
            Err(mpsc::RecvTimeoutError::Timeout) => {}
        }
        if !media.current() {
            if let Some(old) = link.take() {
                old.stop();
            }
            media = Arc::new(Media::empty());
            epoch += 1;
            error = "USB disconnected or changed; waiting for a fresh export".into();
            link = Some(rbl_link::LinkExport::start(
                media.clone(),
                interface.clone(),
                rbl_link::Ports::REKORDBOX,
            )?);
        }
        if report_at.elapsed() >= Duration::from_millis(250) {
            report_at = Instant::now();
            if let Some(current) = &link {
                let snapshot = current.snapshot();
                let players: Vec<_> = snapshot.players.iter().filter(|p| p.kind == rbl_link::DeviceType::Cdj).map(|p| json!({
                    "number": p.number, "name": p.name, "address": p.address.to_string(), "mac": p.mac,
                    "usb": p.usb_present == Some(true) && p.usb_seen.is_some_and(|seen| seen.elapsed() < Duration::from_secs(2)),
                    "generation": format!("{}:{}", epoch, p.usb_generation), "playing": p.playing, "loaded": p.loaded
                })).collect();
                emit(
                    json!({"revision": revision, "address": interface.address.to_string(), "state": format!("{:?}", snapshot.link), "serving": media.database.is_some(), "tracks": media.library.len(), "error": error, "players": players}),
                )?;
            }
        }
    }
    if let Some(current) = link {
        current.stop();
    }
    Ok(())
}

#[cfg(test)]
mod tests;
