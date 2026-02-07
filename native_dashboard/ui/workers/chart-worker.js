/**
 * Chart Worker - Offloads chart calculations to background thread
 * Performance optimization: Moves heavy math operations off the main thread
 */

self.onmessage = function(e) {
    const { type, data } = e.data;
    
    switch (type) {
        case 'calculate':
            const result = calculateChartData(data);
            self.postMessage({ type: 'result', data: result });
            break;
            
        case 'stats':
            const stats = calculateStats(data.values);
            self.postMessage({ type: 'stats', data: stats });
            break;
    }
};

/**
 * Calculate chart rendering data
 */
function calculateChartData(params) {
    const { data, width, height, padding } = params;
    
    if (data.length < 2) {
        return { empty: true };
    }
    
    const values = data.map(d => d.value);
    const minVal = Math.min(...values) * 0.9;
    const maxVal = Math.max(...values) * 1.1 || 1;
    
    // Pre-calculate all points
    const points = data.map((point, i) => ({
        x: padding + (width - padding * 2) * (i / (data.length - 1)),
        y: height - padding - ((point.value - minVal) / (maxVal - minVal)) * (height - padding * 2)
    }));
    
    // Calculate grid lines
    const gridLines = [];
    for (let i = 0; i <= 4; i++) {
        gridLines.push(padding + (height - padding * 2) * (i / 4));
    }
    
    return {
        empty: false,
        points,
        gridLines,
        minVal,
        maxVal,
        currentValue: data[data.length - 1]?.value ?? 0
    };
}

/**
 * Calculate statistics for data set
 */
function calculateStats(values) {
    if (!values || values.length === 0) {
        return { min: 0, max: 0, avg: 0, sum: 0 };
    }
    
    const sum = values.reduce((a, b) => a + b, 0);
    const avg = sum / values.length;
    const min = Math.min(...values);
    const max = Math.max(...values);
    
    // Standard deviation
    const squareDiffs = values.map(value => Math.pow(value - avg, 2));
    const avgSquareDiff = squareDiffs.reduce((a, b) => a + b, 0) / values.length;
    const stdDev = Math.sqrt(avgSquareDiff);
    
    return { min, max, avg, sum, stdDev, count: values.length };
}
