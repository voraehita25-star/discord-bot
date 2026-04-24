use criterion::{Criterion, black_box, criterion_group, criterion_main};
use media_processor::{from_base64, to_base64};
use media_processor::{get_gif_frame_count, is_animated_gif};

fn bench_base64_encode(c: &mut Criterion) {
    let mut group = c.benchmark_group("base64_encode");

    for &size in &[1024, 102_400, 1_048_576] {
        let data: Vec<u8> = (0..size).map(|i| (i % 256) as u8).collect();
        group.bench_function(format!("{size}B"), |bench| {
            bench.iter(|| to_base64(black_box(&data)));
        });
    }

    group.finish();
}

fn bench_base64_decode(c: &mut Criterion) {
    let mut group = c.benchmark_group("base64_decode");

    for &size in &[1024, 102_400] {
        let data: Vec<u8> = (0..size).map(|i| (i % 256) as u8).collect();
        let encoded = to_base64(&data);
        group.bench_function(format!("{size}B"), |bench| {
            bench.iter(|| from_base64(black_box(&encoded)));
        });
    }

    group.finish();
}

fn bench_gif_detection(c: &mut Criterion) {
    // Minimal valid GIF89a with 2 frames
    let animated_gif: Vec<u8> = vec![
        0x47, 0x49, 0x46, 0x38, 0x39, 0x61, // GIF89a
        0x01, 0x00, 0x01, 0x00, 0x00, 0x00, 0x00, // LSD
        0x21, 0xF9, 0x04, 0x00, 0x00, 0x00, 0x00, 0x00, // GCE
        0x2C, 0x00, 0x00, 0x00, 0x00, 0x01, 0x00, 0x01, 0x00, 0x00, // Image 1
        0x02, 0x02, 0x44, 0x01, 0x00,
        0x21, 0xF9, 0x04, 0x00, 0x00, 0x00, 0x00, 0x00, // GCE
        0x2C, 0x00, 0x00, 0x00, 0x00, 0x01, 0x00, 0x01, 0x00, 0x00, // Image 2
        0x02, 0x02, 0x44, 0x01, 0x00,
        0x3B, // Trailer
    ];

    c.bench_function("is_animated_gif", |bench| {
        bench.iter(|| is_animated_gif(black_box(&animated_gif)));
    });

    c.bench_function("get_gif_frame_count", |bench| {
        bench.iter(|| get_gif_frame_count(black_box(&animated_gif)));
    });
}

criterion_group!(benches, bench_base64_encode, bench_base64_decode, bench_gif_detection);
criterion_main!(benches);
