use criterion::{Criterion, black_box, criterion_group, criterion_main};
use rag_engine::cosine_similarity;

fn bench_cosine_similarity(c: &mut Criterion) {
    let mut group = c.benchmark_group("cosine_similarity");

    for size in [128, 512, 1024] {
        let a: Vec<f32> = (0..size).map(|i| (i as f32 * 0.01).sin()).collect();
        let b: Vec<f32> = (0..size).map(|i| (i as f32 * 0.02).cos()).collect();

        group.bench_function(format!("dim_{size}"), |bench| {
            bench.iter(|| cosine_similarity(black_box(&a), black_box(&b)));
        });
    }

    group.finish();
}

criterion_group!(benches, bench_cosine_similarity);
criterion_main!(benches);
