/**
 * Log Processor Worker - Processes and filters logs in background
 * Performance optimization: Handles large log data without blocking UI
 */

self.onmessage = function(e) {
    const { type, data } = e.data;
    
    switch (type) {
        case 'process':
            const result = processLogs(data.logs, data.filter, data.search);
            self.postMessage({ type: 'processed', data: result });
            break;
            
        case 'search':
            const searchResult = searchLogs(data.logs, data.query);
            self.postMessage({ type: 'searchResult', data: searchResult });
            break;
    }
};

/**
 * Process and filter logs
 */
function processLogs(logs, filter, search) {
    const processed = [];
    const levelCounts = { info: 0, warning: 0, error: 0, debug: 0 };
    
    for (let i = 0; i < logs.length; i++) {
        const line = logs[i];
        let level = 'info';
        
        if (line.includes('ERROR')) {
            level = 'error';
            levelCounts.error++;
        } else if (line.includes('WARNING')) {
            level = 'warning';
            levelCounts.warning++;
        } else if (line.includes('DEBUG')) {
            level = 'debug';
            levelCounts.debug++;
        } else {
            levelCounts.info++;
        }
        
        // Apply filter
        const passesFilter = filter === 'all' || line.includes(filter);
        
        // Apply search if provided
        const passesSearch = !search || line.toLowerCase().includes(search.toLowerCase());
        
        if (passesFilter && passesSearch) {
            processed.push({
                index: i,
                text: line,
                level: level
            });
        }
    }
    
    return {
        logs: processed,
        total: logs.length,
        filtered: processed.length,
        counts: levelCounts
    };
}

/**
 * Search logs with fuzzy matching
 */
function searchLogs(logs, query) {
    if (!query || query.length < 2) {
        return { matches: [], query };
    }
    
    const queryLower = query.toLowerCase();
    const matches = [];
    
    for (let i = 0; i < logs.length; i++) {
        const line = logs[i];
        const lineLower = line.toLowerCase();
        const index = lineLower.indexOf(queryLower);
        
        if (index !== -1) {
            matches.push({
                lineIndex: i,
                matchStart: index,
                matchEnd: index + query.length,
                text: line,
                context: getContext(line, index, query.length)
            });
        }
    }
    
    return { matches, query, total: matches.length };
}

/**
 * Get context around a match
 */
function getContext(line, matchIndex, matchLength) {
    const contextSize = 30;
    const start = Math.max(0, matchIndex - contextSize);
    const end = Math.min(line.length, matchIndex + matchLength + contextSize);
    
    let context = line.substring(start, end);
    if (start > 0) context = '...' + context;
    if (end < line.length) context = context + '...';
    
    return context;
}
