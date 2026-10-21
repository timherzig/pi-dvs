use super::*;
use rbl_dbserver::{kind, Argument};
use rbl_fakecdj::{database_port, mount, Database};
use std::net::{Ipv4Addr, TcpListener, UdpSocket};

fn fixture(file_type: u8, generation: u32) -> (tempfile::TempDir, Arc<Media>, Vec<u8>, PathBuf) {
    let dir = tempfile::tempdir().unwrap();
    let root = dir.path().canonicalize().unwrap();
    std::fs::create_dir_all(root.join("PIONEER/rekordbox")).unwrap();
    let db = root.join("PIONEER/rekordbox/export.pdb");
    std::fs::write(&db, b"synthetic catalog identity").unwrap();
    let path = root.join("test.wav");
    let bytes: Vec<u8> = (0..90_001).map(|n| (n % 251) as u8).collect();
    std::fs::write(&path, &bytes).unwrap();
    let catalog = Catalog {
        generation,
        root,
        database: db,
        tracks: vec![Track {
            id: 1,
            title: "Protocol fixture".into(),
            artist: "Artist".into(),
            album: "Album".into(),
            path: path.to_str().unwrap().into(),
            file_type,
            ..Default::default()
        }],
        playlists: vec![Playlist {
            id: 11,
            name: "Playlist".into(),
            parent: None,
            folder: false,
            order: 0,
            tracks: vec![1],
        }],
    };
    let media = Arc::new(Media::load(catalog).unwrap());
    (dir, media, bytes, path)
}
fn start(media: Arc<Media>) -> rbl_link::LinkExport {
    let link = rbl_link::LinkExport::start(
        media,
        rbl_link::Interface::loopback(),
        rbl_link::Ports::EPHEMERAL,
    )
    .unwrap();
    let hex = "5173707431576d4a4f4c060043444a2d393030000000000000000000000000000102003601010200000000017f000001020000000100";
    let packet: Vec<u8> = (0..hex.len())
        .step_by(2)
        .map(|i| u8::from_str_radix(&hex[i..i + 2], 16).unwrap())
        .collect();
    let sender = UdpSocket::bind((Ipv4Addr::LOCALHOST, 0)).unwrap();
    sender
        .send_to(&packet, (Ipv4Addr::LOCALHOST, link.beacon_ports().0))
        .unwrap();
    let deadline = Instant::now() + Duration::from_secs(10);
    while !matches!(link.link_state(), rbl_link::LinkState::Up { .. }) {
        assert!(Instant::now() < deadline, "join did not complete");
        std::thread::sleep(Duration::from_millis(25));
    }
    link
}
#[test]
fn concurrent_clients_browse_and_read_exact_files_and_shutdown_releases_ports() {
    let (_dir, media, bytes, path) = fixture(11, 0x12000000);
    let link = start(media);
    let port = database_port(link.query_address()).unwrap();
    assert_eq!(port, link.database_address().port());
    let mut one = Database::connect(link.database_address(), 1).unwrap();
    let mut two = Database::connect(link.database_address(), 2).unwrap();
    assert_eq!(
        one.request(
            kind::TRACK_MENU,
            vec![Argument::Number(0x0101_0301), Argument::Number(0)]
        )
        .unwrap()[0]
            .arguments[1],
        Argument::Number(1)
    );
    assert_eq!(
        two.request(
            kind::ARTIST_MENU,
            vec![Argument::Number(0x0201_0301), Argument::Number(0)]
        )
        .unwrap()[0]
            .arguments[1],
        Argument::Number(1)
    );
    let path = path.to_str().unwrap().trim_start_matches('/');
    let address = link.portmap_address();
    let read = || {
        let mut client = mount(address, "/").unwrap();
        client.read_file(path).unwrap()
    };
    std::thread::scope(|scope| {
        let first = scope.spawn(read);
        let second = scope.spawn(read);
        assert_eq!(first.join().unwrap(), bytes);
        assert_eq!(second.join().unwrap(), bytes);
    });
    let query = link.query_address();
    drop(one);
    drop(two);
    link.stop();
    assert!(TcpListener::bind(query).is_ok());
}
#[test]
fn exact_file_allowlist_and_removal_fail_closed() {
    let (_dir, media, bytes, path) = fixture(12, 50000);
    let neighbor = path.with_file_name("private.txt");
    std::fs::write(&neighbor, b"not in export").unwrap();
    let link = start(media.clone());
    let mut client = mount(link.portmap_address(), "/").unwrap();
    assert!(client
        .read_file(neighbor.to_str().unwrap().trim_start_matches('/'))
        .is_err());
    assert!(client.read_file("etc/passwd").is_err());
    let relative = path.to_str().unwrap().trim_start_matches('/');
    assert_eq!(client.read_file(relative).unwrap(), bytes);
    std::fs::remove_file(&path).unwrap();
    std::fs::write(&path, b"replacement file at same path").unwrap();
    assert!(client.read_file(relative).is_err());
    std::fs::remove_file(&media.database.as_ref().unwrap().0).unwrap();
    assert!(media.library().is_none());
    link.stop();
}
#[test]
fn reconnect_assigns_new_handles_even_when_track_ids_and_paths_are_reused() {
    let (_dir, media, _, path) = fixture(11, 10000);
    let old = media.file_exports(&media.library);
    let tree = old.get("/").unwrap();
    let node = tree
        .resolve(path.to_str().unwrap().trim_start_matches('/'))
        .unwrap();
    let handle = tree.handle(node).unwrap();
    let mut replacement = rbl_nfs::Vfs::new("/");
    replacement.add_file_unsized(path.to_str().unwrap().trim_start_matches('/'), &path);
    let mut exports = rbl_nfs::Exports::with_id_base(20000);
    exports.insert(replacement);
    assert!(exports.get("/").unwrap().node_of(&handle).is_none());
}
#[test]
fn mp3_wav_aiff_decoder_selectors_and_artist_album_browsing() {
    for file_type in [1, 11, 12] {
        let (_dir, media, _, _) = fixture(file_type, 10000);
        let catalog = rbl_link::catalog::IndexCatalog::new(media.clone(), Default::default());
        assert!(!rbl_dbserver::catalog::Catalog::list(
            &catalog,
            &rbl_dbserver::catalog::Query::ArtistAlbums(1)
        )
        .is_empty());
        let link = start(media);
        let mut client = Database::connect(link.database_address(), 1).unwrap();
        let answer = client
            .request(
                kind::TRACK_INFO,
                vec![Argument::Number(0x0108_0301), Argument::Number(1)],
            )
            .unwrap();
        assert_eq!(answer[0].arguments[1], Argument::Number(7));
        let mut rows = client
            .request(
                kind::RENDER,
                [0x0108_0301, 0, 7, 0, 7, 0]
                    .into_iter()
                    .map(Argument::Number)
                    .collect(),
            )
            .unwrap();
        while !rows.iter().any(|r| r.kind == kind::MENU_FOOTER) {
            let more = client.receive().unwrap();
            assert!(!more.is_empty());
            rows.extend(more);
        }
        let title = rows.iter().find(|r| r.kind == kind::MENU_ITEM).unwrap();
        assert_eq!(title.arguments[1], Argument::Number(u32::from(file_type)));
        link.stop();
    }
}

#[test]
fn assets_are_allowlisted_bounded_and_checked_again_after_change() {
    use std::os::unix::fs::symlink;
    let (_dir, mut media, _, _) = fixture(11, 1234);
    let outside = tempfile::NamedTempFile::new().unwrap();
    let dat = media.root.join("safe.DAT");
    std::fs::write(&dat, b"synthetic analysis").unwrap();
    let ext = media.root.join("safe.EXT");
    symlink(outside.path(), &ext).unwrap();
    let mutable = Arc::get_mut(&mut media).unwrap();
    mutable
        .assets
        .insert(dat.clone(), Stamp::read(&dat).unwrap());
    assert_eq!(media.read_asset(&dat, 100).unwrap(), b"synthetic analysis");
    assert!(media.read_asset(&dat, 2).is_none());
    assert!(media.read_asset(&ext, 100).is_none());
    std::fs::write(&dat, b"changed analysis").unwrap();
    assert!(media.read_asset(&dat, 100).is_none());
}

#[test]
fn in_root_path_alias_is_canonicalized_and_external_alias_is_rejected() {
    use std::os::unix::fs::symlink;
    let (_dir, original, _, path) = fixture(11, 10000);
    let alias = path.with_file_name("alias.wav");
    symlink(&path, &alias).unwrap();
    let load = |path: &Path| {
        Media::load(Catalog {
            generation: 20000,
            root: original.root.clone(),
            database: original.database.as_ref().unwrap().0.clone(),
            tracks: vec![Track {
                id: 1,
                path: path.to_str().unwrap().into(),
                file_type: 11,
                ..Default::default()
            }],
            playlists: vec![],
        })
    };
    let from_alias = load(&alias).unwrap();
    assert!(from_alias.files.contains_key(&path));
    assert_eq!(
        from_alias.library.folder_path.get(0),
        path.to_str().unwrap()
    );
    let outside = tempfile::NamedTempFile::new().unwrap();
    std::fs::remove_file(&alias).unwrap();
    symlink(outside.path(), &alias).unwrap();
    assert!(load(&alias).is_err());
}

#[test]
fn unicode_names_retain_sort_and_search_keys_in_a_mixed_library() {
    use rbl_dbserver::catalog::{Catalog as _, Query, Row, Sort, TrackScope};
    let names = ["صبار", "東京", "Мама", "Mii Channel Edit", "Éclair"];
    let tracks: Vec<_> = names
        .iter()
        .enumerate()
        .map(|(i, title)| TrackInput {
            id: i as u64 + 1,
            title,
            artist: title,
            ..Default::default()
        })
        .collect();
    let mut media = Media::empty();
    media.library = Arc::new(library_from(&tracks));
    for (i, title) in names.iter().enumerate() {
        assert!(
            !media.library.title_folded.get(i).is_empty(),
            "lost key for {title}"
        );
        assert_eq!(media.library.title.get(i), *title);
    }
    let catalog = rbl_link::catalog::IndexCatalog::new(Arc::new(media), Default::default());
    let rows = catalog.list(&Query::Tracks {
        scope: TrackScope::All,
        sort: Sort::Alphabet,
    });
    assert!(matches!(rows[0], Row::Track { id: 5, .. }));
    assert!(matches!(rows[1], Row::Track { id: 4, .. }));
    let artists = catalog.list(&Query::Artists(Sort::Alphabet));
    assert!(matches!(&artists[0], Row::Named { name, .. } if name == "Éclair"));
    assert_eq!(rbl_index::strings::fold("CAFÉ!"), "cafe");
}

#[test]
fn repeated_artists_and_albums_share_one_browsable_entity() {
    use rbl_dbserver::catalog::{Catalog as _, Query, Row, Sort, TrackScope};
    let tracks = ["First", "Second"].map(|title| TrackInput {
        id: if title == "First" { 1 } else { 2 },
        title,
        artist: "Shared artist",
        album: "Shared album",
        genre: "House",
        label: "Label",
        ..Default::default()
    });
    let mut media = Media::empty();
    media.library = Arc::new(library_from(&tracks));
    assert_eq!(media.library.genres.len(), 1);
    assert_eq!(media.library.labels.len(), 1);
    let catalog = rbl_link::catalog::IndexCatalog::new(Arc::new(media), Default::default());
    let artists = catalog.list(&Query::Artists(Sort::Alphabet));
    assert_eq!(artists.len(), 1);
    let Row::Named { id: artist, .. } = artists[0] else {
        panic!("missing artist");
    };
    let albums = catalog.list(&Query::ArtistAlbums(artist));
    assert_eq!(albums.len(), 1);
    let Row::Named { id: album, .. } = albums[0] else {
        panic!("missing album");
    };
    let rows = catalog.list(&Query::Tracks {
        scope: TrackScope::Artist {
            artist,
            album: Some(album),
        },
        sort: Sort::Alphabet,
    });
    assert_eq!(rows.len(), 2);
}

#[test]
fn cdj900_search_selection_resolves_the_requested_track() {
    use rbl_dbserver::net::Session;
    use rbl_dbserver::session::LinkSession;
    use rbl_dbserver::Message;
    let tracks = [
        TrackInput {
            id: 79,
            title: "A previous track",
            ..Default::default()
        },
        TrackInput {
            id: 809,
            title: "Mii Channel Edit",
            ..Default::default()
        },
    ];
    let mut media = Media::empty();
    media.library = Arc::new(library_from(&tracks));
    let catalog = rbl_link::catalog::IndexCatalog::new(Arc::new(media), Default::default());
    let mut session = LinkSession::new(Arc::new(catalog));
    session.handle(&Message::new(1, kind::SETUP, vec![Argument::Number(2)]));
    let search = session.handle(&Message::new(
        2,
        kind::SEARCH,
        vec![
            Argument::Number(0x0201_0101),
            Argument::Number(0),
            Argument::Number(8),
            Argument::String("MII".into()),
            Argument::Number(0),
        ],
    ));
    assert_eq!(search[0].arguments[1], Argument::Number(1));
    let numbers = |kind, tx, values: &[u32]| {
        Message::new(
            tx,
            kind,
            values.iter().copied().map(Argument::Number).collect(),
        )
    };
    let search_rows = session.handle(&numbers(kind::RENDER, 3, &[0x0201_0101, 0, 1, 0, 1, 0]));
    assert_eq!(search_rows[1].arguments[1], Argument::Number(809));
    // Captured CDJ-900 load transition: the third argument is the selected ID.
    let selection = session.handle(&numbers(kind::CONTENT_TRACKS, 4, &[0x0203_0101, 0, 809]));
    assert_eq!(selection[0].arguments[1], Argument::Number(1));
    let selected = session.handle(&numbers(kind::RENDER, 5, &[0x0203_0101, 0, 1, 0, 1, 0]));
    assert_eq!(selected[1].arguments[1], Argument::Number(809));
    assert_eq!(
        selected[1].arguments[3],
        Argument::String("Mii Channel Edit".into())
    );
    let missing = session.handle(&numbers(kind::CONTENT_TRACKS, 6, &[0x0203_0101, 0, 999]));
    assert_eq!(missing[0].arguments[1], Argument::Number(0));
    // The RX3 two-argument form remains the full sorted library.
    let all = session.handle(&numbers(kind::CONTENT_TRACKS, 7, &[0x0203_0101, 0]));
    assert_eq!(all[0].arguments[1], Argument::Number(2));
}

#[test]
fn mixed_library_artist_album_routes_return_their_tracks() {
    use rbl_dbserver::catalog::{Catalog as _, Query, Row, Sort, TrackScope};
    let tracks = [
        TrackInput {
            id: 1,
            title: "First",
            artist: "Earlier artist",
            album: "Earlier album",
            genre: "House",
            label: "First label",
            ..Default::default()
        },
        TrackInput {
            id: 2,
            title: "Second",
            artist: "Earlier artist",
            album: "Earlier album",
            genre: "House",
            label: "First label",
            ..Default::default()
        },
        TrackInput {
            id: 590,
            title: "This Old House",
            artist: "A.A.L",
            album: "2012 - 2017",
            genre: "Electronic",
            label: "Other label",
            ..Default::default()
        },
        TrackInput {
            id: 591,
            title: "Another",
            artist: "A.A.L",
            album: "2012 - 2017",
            genre: "Electronic",
            label: "Other label",
            ..Default::default()
        },
        TrackInput {
            id: 809,
            title: "Mii",
            artist: "Trickpony",
            album: "Mii",
            genre: "Edit",
            label: "Third label",
            ..Default::default()
        },
    ];
    let mut media = Media::empty();
    media.library = Arc::new(library_from(&tracks));
    let catalog = rbl_link::catalog::IndexCatalog::new(Arc::new(media), Default::default());
    for artist_row in catalog.list(&Query::Artists(Sort::Alphabet)) {
        let Row::Named { id: artist, name } = artist_row else {
            panic!("missing artist")
        };
        let mut actual = Vec::new();
        for album_row in catalog.list(&Query::ArtistAlbums(artist)) {
            let Row::Named { id: album, .. } = album_row else {
                panic!("missing album")
            };
            actual.extend(
                catalog
                    .list(&Query::Tracks {
                        scope: TrackScope::Artist {
                            artist,
                            album: Some(album),
                        },
                        sort: Sort::Alphabet,
                    })
                    .into_iter()
                    .map(|row| {
                        let Row::Track { id, .. } = row else {
                            panic!("missing track")
                        };
                        id
                    }),
            );
        }
        actual.sort_unstable();
        let mut expected: Vec<_> = tracks
            .iter()
            .filter(|t| t.artist == name)
            .map(|t| t.id as u32)
            .collect();
        expected.sort_unstable();
        assert_eq!(actual, expected, "incorrect artist/album route for {name}");
    }
    for track in &tracks {
        let details = catalog.track(track.id as u32).unwrap();
        let rows = catalog.list(&Query::Tracks {
            scope: TrackScope::Artist {
                artist: details.artist_id,
                album: Some(details.album_id),
            },
            sort: Sort::Alphabet,
        });
        assert!(
            rows.iter()
                .any(|r| matches!(r, Row::Track { id, .. } if u64::from(*id) == track.id)),
            "metadata cannot round-trip {}",
            track.title
        );
    }
}

#[test]
fn paced_duplicate_rechecks_media_and_metadata_has_bounded_delay() {
    use rbl_nfs::{
        nfs_proc, nfs_status,
        rpc::{Auth, Call, Reply},
        xdr::{Reader, Writer},
    };
    let (_dir, mut media, _, path) = fixture(11, 12345);
    let library = Arc::get_mut(&mut Arc::get_mut(&mut media).unwrap().library).unwrap();
    library.sample_rate[0] = 44_100;
    library.bit_depth[0] = 16;
    let server = rbl_nfs::net::Bound::start(
        media.file_exports(&media.library),
        Ipv4Addr::LOCALHOST.into(),
        0,
        0,
        0,
        None,
        None,
    )
    .unwrap();
    let mut mounted = mount(server.portmap_address(), "/").unwrap();
    let handle = mounted
        .resolve(path.to_str().unwrap().trim_start_matches('/'))
        .unwrap();
    let socket = UdpSocket::bind((Ipv4Addr::LOCALHOST, 0)).unwrap();
    socket
        .set_read_timeout(Some(Duration::from_secs(1)))
        .unwrap();
    let mut args = Writer::new();
    args.opaque_fixed(&handle)
        .u32(0)
        .u32(rbl_nfs::MAX_READ as u32)
        .u32(0);
    let arguments = args.into_bytes();
    let request = |xid, procedure, arguments| {
        Call {
            xid,
            program: rbl_nfs::PROGRAM_NFS,
            version: rbl_nfs::VERSION_NFS,
            procedure,
            credential: Auth::null(),
            verifier: Auth::null(),
            arguments,
        }
        .encode()
    };
    let read = request(700, nfs_proc::READ, &arguments);
    let mut buffer = vec![0; 65535];
    socket.send_to(&read, server.nfs_address()).unwrap();
    let size = socket.recv(&mut buffer).unwrap();
    let reply = Reply::decode(&buffer[..size]).unwrap();
    assert_eq!(Reader::new(reply.results).u32().unwrap(), nfs_status::OK);
    let started = Instant::now();
    // Same XID, peer and body exercises cached replay, queued behind its budget.
    socket.send_to(&read, server.nfs_address()).unwrap();
    let metadata = request(701, nfs_proc::GETATTR, &handle);
    socket.send_to(&metadata, server.nfs_address()).unwrap();
    std::fs::remove_file(&path).unwrap();
    for xid in [700, 701] {
        let size = socket.recv(&mut buffer).unwrap();
        let reply = Reply::decode(&buffer[..size]).unwrap();
        assert_eq!(reply.xid, xid);
        assert_eq!(Reader::new(reply.results).u32().unwrap(), nfs_status::STALE);
    }
    assert!(started.elapsed() >= Duration::from_millis(200));
    assert!(started.elapsed() < Duration::from_millis(600));
    server.shutdown();
}

#[test]
fn reused_read_xid_with_a_new_offset_returns_the_requested_audio() {
    use rbl_nfs::{
        nfs_proc,
        rpc::{Auth, Call, Reply},
        xdr::{Reader, Writer},
    };
    let (_dir, media, bytes, path) = fixture(11, 12345);
    let exports = media.file_exports(&media.library);
    let tree = exports.get("/").unwrap();
    let index = tree
        .resolve(path.to_str().unwrap().trim_start_matches('/'))
        .unwrap();
    let handle = tree.handle(index).unwrap();
    let server = rbl_nfs::Server::new(exports, 0, 0);
    for offset in [0, 1280, 0] {
        let mut args = Writer::new();
        args.opaque_fixed(handle.as_bytes())
            .u32(offset)
            .u32(1280)
            .u32(0);
        let arguments = args.into_bytes();
        let request = Call {
            xid: 77,
            program: rbl_nfs::PROGRAM_NFS,
            version: rbl_nfs::VERSION_NFS,
            procedure: nfs_proc::READ,
            credential: Auth::null(),
            verifier: Auth::null(),
            arguments: &arguments,
        }
        .encode();
        let reply = server.handle(&request).unwrap();
        let reply = Reply::decode(&reply).unwrap();
        let mut reader = Reader::new(reply.results);
        for _ in 0..18 {
            reader.u32().unwrap();
        }
        assert_eq!(
            reader.opaque().unwrap(),
            &bytes[offset as usize..offset as usize + 1280]
        );
    }
}

#[test]
fn metadata_preserves_pcm_bitrate_without_an_optional_database_backend() {
    use rbl_dbserver::net::Session;
    use rbl_dbserver::session::LinkSession;
    use rbl_dbserver::Message;
    for (file_type, bitrate) in [(12, 1411), (11, 2304), (1, 320), (1, 0)] {
        let mut media = Media::empty();
        media.library = Arc::new(library_from(&[TrackInput {
            id: 590,
            title: "Bitrate fixture",
            file_type,
            bitrate,
            ..Default::default()
        }]));
        let catalog = rbl_link::catalog::IndexCatalog::new(Arc::new(media), Default::default());
        let mut session = LinkSession::new(Arc::new(catalog));
        session.handle(&Message::new(1, kind::SETUP, vec![Argument::Number(2)]));
        let metadata = session.handle(&Message::new(
            2,
            kind::METADATA,
            vec![Argument::Number(0x0203_0101), Argument::Number(590)],
        ));
        assert_eq!(metadata[0].arguments[1], Argument::Number(16));
        let rows = session.handle(&Message::new(
            3,
            kind::RENDER,
            [0x0203_0101, 0, 16, 0, 16, 0]
                .into_iter()
                .map(Argument::Number)
                .collect(),
        ));
        let row = rows
            .iter()
            .find(|row| row.kind == kind::MENU_ITEM && row.arguments[6] == Argument::Number(0x10))
            .unwrap();
        assert_eq!(row.arguments[1], Argument::Number(bitrate));
    }
}

#[test]
fn cdj900_full_blocks_are_paced_without_changing_audio_or_retry_bytes() {
    use rbl_nfs::{
        nfs_proc,
        rpc::{Auth, Call, Reply},
        xdr::{Reader, Writer},
    };
    let (_dir, mut media, bytes, path) = fixture(12, 12345);
    let library = Arc::get_mut(&mut Arc::get_mut(&mut media).unwrap().library).unwrap();
    library.sample_rate[0] = 44_100;
    library.bit_depth[0] = 16;
    library.bitrate[0] = 1411;
    let server = rbl_nfs::net::Bound::start(
        media.file_exports(&media.library),
        Ipv4Addr::LOCALHOST.into(),
        0,
        0,
        0,
        None,
        None,
    )
    .unwrap();
    let mut mounted = mount(server.portmap_address(), "/").unwrap();
    let handle = mounted
        .resolve(path.to_str().unwrap().trim_start_matches('/'))
        .unwrap();
    let socket = UdpSocket::bind((Ipv4Addr::LOCALHOST, 0)).unwrap();
    socket
        .set_read_timeout(Some(Duration::from_secs(2)))
        .unwrap();
    let mut buffer = vec![0; 65535];
    let mut first = None;
    for block in [0, 1, 1, 2, 3, 4, 5, 6] {
        let offset = block * 9408;
        let mut args = Writer::new();
        args.opaque_fixed(&handle).u32(offset).u32(9408).u32(0);
        let arguments = args.into_bytes();
        let request = Call {
            xid: 800 + block,
            program: rbl_nfs::PROGRAM_NFS,
            version: rbl_nfs::VERSION_NFS,
            procedure: nfs_proc::READ,
            credential: Auth::null(),
            verifier: Auth::null(),
            arguments: &arguments,
        }
        .encode();
        socket.send_to(&request, server.nfs_address()).unwrap();
        let size = socket.recv(&mut buffer).unwrap();
        first.get_or_insert_with(Instant::now);
        assert_eq!(size, 9508, "CDJ requires the full requested block");
        let reply = Reply::decode(&buffer[..size]).unwrap();
        assert_eq!(reply.xid, 800 + block);
        let mut reader = Reader::new(reply.results);
        for _ in 0..18 {
            reader.u32().unwrap();
        }
        assert_eq!(
            reader.opaque().unwrap(),
            &bytes[offset as usize..offset as usize + 9408]
        );
    }
    // Seven gaps need ~254 ms at the hardware-tested compatibility rate.
    // This fails against the prior 512 KiB/s policy (~127 ms), including replay.
    assert!(
        first.unwrap().elapsed() >= Duration::from_millis(220),
        "replies exceeded the CDJ-900 compatibility budget"
    );
    server.shutdown();
}

#[test]
fn read_budgets_follow_file_handles_without_raising_other_tracks() {
    use rbl_nfs::{
        nfs_proc,
        rpc::{Auth, Call},
        xdr::Writer,
    };
    let (_dir, original, bytes, path) = fixture(12, 12345);
    let higher = path.with_file_name("higher.aiff");
    std::fs::write(&higher, bytes).unwrap();
    let track = |id, path: &Path, sample_rate, bit_depth| Track {
        id,
        path: path.to_str().unwrap().into(),
        file_type: 12,
        sample_rate,
        bit_depth,
        ..Default::default()
    };
    let load = |alias| {
        let mut tracks = vec![track(1, &path, 44_100, 16), track(2, &higher, 48_000, 24)];
        if alias {
            tracks.push(track(3, &path, 48_000, 24));
            tracks.reverse();
        }
        Media::load(Catalog {
            generation: 12345,
            root: original.root.clone(),
            database: original.database.as_ref().unwrap().0.clone(),
            tracks,
            playlists: vec![],
        })
        .unwrap()
    };
    let request = |tree: &rbl_nfs::Vfs, path: &Path| {
        let index = tree
            .resolve(path.to_str().unwrap().trim_start_matches('/'))
            .unwrap();
        let mut args = Writer::new();
        args.opaque_fixed(tree.handle(index).unwrap().as_bytes())
            .u32(0)
            .u32(9408)
            .u32(0);
        let arguments = args.into_bytes();
        Call {
            xid: 900,
            program: rbl_nfs::PROGRAM_NFS,
            version: rbl_nfs::VERSION_NFS,
            procedure: nfs_proc::READ,
            credential: Auth::null(),
            verifier: Auth::null(),
            arguments: &arguments,
        }
        .encode()
    };
    let media = load(false);
    let exports = media.file_exports(&media.library);
    let low = request(exports.get("/").unwrap(), &path);
    let high = request(exports.get("/").unwrap(), &higher);
    let server = rbl_nfs::Server::new(exports, 0, 0);
    assert_eq!(server.read_rate(&low).get(), 262_144);
    assert_eq!(server.read_rate(&high).get(), 403_200);
    assert_eq!(server.read_rate(&low).get(), 262_144);
    assert_eq!(server.read_rate(b"invalid").get(), 524_288);
    let aliases = load(true);
    let exports = aliases.file_exports(&aliases.library);
    let alias = request(exports.get("/").unwrap(), &path);
    assert_eq!(
        rbl_nfs::Server::new(exports, 0, 0).read_rate(&alias).get(),
        403_200
    );
    // Rate lookup is in-memory; deletion does not turn it into file I/O.
    std::fs::remove_file(&path).unwrap();
    assert_eq!(server.read_rate(&low).get(), 262_144);
}

#[test]
fn nominal_read_policy_bounds_unknown_metadata_and_preserves_pcm_throughput() {
    assert_eq!(serving_read_rate(12, 44_100, 16, 1411).get(), 262_144);
    assert_eq!(serving_read_rate(11, 48_000, 24, 0).get(), 403_200);
    assert_eq!(serving_read_rate(1, 44_100, 0, 320).get(), 262_144);
    assert_eq!(serving_read_rate(4, 44_100, 0, 0).get(), 524_288);
    assert_eq!(
        serving_read_rate(12, u32::MAX, u16::MAX, u32::MAX).get(),
        524_288
    );
}
