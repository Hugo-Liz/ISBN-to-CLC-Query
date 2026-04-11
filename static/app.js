// app.js - 前端交互逻辑

// ==================== 全局状态 ====================
let currentFile = null;       // 当前选中的上传文件
let batchResults = [];        // 批量查询结果缓存（用于导出）

// ==================== 标签切换 ====================
document.querySelectorAll('.tab').forEach(tab => {
    tab.addEventListener('click', () => {
        const tabName = tab.dataset.tab;

        // 切换标签激活状态
        document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
        tab.classList.add('active');

        // 切换面板
        document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
        document.getElementById(`panel-${tabName}`).classList.add('active');
    });
});

// ==================== 单条查询 ====================

// 回车触发查询
document.getElementById('isbn-input').addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
        doSingleQuery();
    }
});

function doSingleQuery() {
    const input = document.getElementById('isbn-input');
    const isbn = input.value.trim();

    if (!isbn) {
        showSingleError('请输入 ISBN 号');
        return;
    }

    // 隐藏之前的结果和错误
    hideElement('single-result');
    hideElement('single-error');
    showElement('single-loading');

    // 禁用按钮
    const btn = document.getElementById('btn-search');
    btn.disabled = true;

    fetch('/api/query', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ isbn: isbn })
    })
    .then(res => res.json())
    .then(data => {
        hideElement('single-loading');
        btn.disabled = false;

        if (data.success) {
            showSingleResult(data);
        } else {
            showSingleError(data.error || '查询失败');
        }
    })
    .catch(err => {
        hideElement('single-loading');
        btn.disabled = false;
        showSingleError('网络请求失败，请检查网络连接');
        console.error('查询出错:', err);
    });
}

function showSingleResult(data) {
    document.getElementById('result-title').textContent = data.title || '未知书名';
    document.getElementById('result-isbn').textContent = `ISBN: ${data.isbn}`;
    document.getElementById('result-authors').textContent = data.authors || '-';
    document.getElementById('result-publisher').textContent = data.publisher || '-';
    document.getElementById('result-pubdate').textContent = data.pubdate || '-';
    document.getElementById('result-clc-code').textContent = data.clc_code || '-';

    // 构建分类路径 DOM
    const pathContainer = document.getElementById('result-clc-path');
    pathContainer.innerHTML = '';

    if (data.clc_path && data.clc_path.length > 0) {
        data.clc_path.forEach((item, index) => {
            // 路径节点
            const span = document.createElement('span');
            span.className = 'path-item';
            span.textContent = item;
            pathContainer.appendChild(span);

            // 箭头（非最后一个）
            if (index < data.clc_path.length - 1) {
                const arrow = document.createElement('span');
                arrow.className = 'path-arrow';
                arrow.textContent = '→';
                pathContainer.appendChild(arrow);
            }
        });
    } else {
        const empty = document.createElement('span');
        empty.style.color = 'var(--text-muted)';
        empty.textContent = '暂无分类路径信息';
        pathContainer.appendChild(empty);
    }

    // 展示主题字段
    const subjectSection = document.getElementById('result-subject-section');
    const subjectEl = document.getElementById('result-subject');
    if (data.subject && data.subject.trim()) {
        subjectEl.textContent = data.subject;
        subjectSection.classList.remove('hidden');
    } else {
        subjectSection.classList.add('hidden');
    }

    showElement('single-result');
}

function showSingleError(message) {
    document.getElementById('single-error-msg').textContent = message;
    showElement('single-error');
}

// ==================== 文件上传 ====================

const uploadZone = document.getElementById('upload-zone');
const fileInput = document.getElementById('file-input');

// 点击上传区域触发文件选择
uploadZone.addEventListener('click', () => {
    fileInput.click();
});

// 文件选择变更
fileInput.addEventListener('change', (e) => {
    if (e.target.files.length > 0) {
        handleFile(e.target.files[0]);
    }
});

// 拖拽事件
uploadZone.addEventListener('dragover', (e) => {
    e.preventDefault();
    uploadZone.classList.add('dragover');
});

uploadZone.addEventListener('dragleave', () => {
    uploadZone.classList.remove('dragover');
});

uploadZone.addEventListener('drop', (e) => {
    e.preventDefault();
    uploadZone.classList.remove('dragover');
    if (e.dataTransfer.files.length > 0) {
        handleFile(e.dataTransfer.files[0]);
    }
});

function handleFile(file) {
    const ext = file.name.split('.').pop().toLowerCase();
    const allowed = ['csv', 'xlsx', 'xls', 'txt'];

    if (!allowed.includes(ext)) {
        showBatchError(`不支持的文件格式 ".${ext}"，支持: ${allowed.join(', ')}`);
        return;
    }

    currentFile = file;

    // 显示文件信息，隐藏上传区域
    document.getElementById('file-name').textContent = file.name;
    hideElement('upload-zone');
    hideElement('batch-error');
    hideElement('batch-results');
    showElement('file-info');
}

function clearFile() {
    currentFile = null;
    fileInput.value = '';
    hideElement('file-info');
    hideElement('batch-progress');
    hideElement('batch-results');
    hideElement('batch-error');
    showElement('upload-zone');
}

// ==================== 批量查询 ====================

function doBatchQuery() {
    if (!currentFile) {
        showBatchError('请先选择文件');
        return;
    }

    // 隐藏之前的结果
    hideElement('batch-results');
    hideElement('batch-error');

    // 显示进度条
    showElement('batch-progress');
    document.getElementById('progress-fill').style.width = '0%';
    document.getElementById('progress-text').textContent = '正在上传文件并查询...';

    // 禁用按钮
    const btn = document.getElementById('btn-batch-query');
    btn.disabled = true;

    const formData = new FormData();
    formData.append('file', currentFile);

    // 模拟进度动画（因为请求是整体返回的）
    let progress = 0;
    const progressInterval = setInterval(() => {
        if (progress < 90) {
            progress += Math.random() * 5;
            document.getElementById('progress-fill').style.width = `${Math.min(progress, 90)}%`;
        }
    }, 500);

    fetch('/api/batch', {
        method: 'POST',
        body: formData
    })
    .then(res => res.json())
    .then(data => {
        clearInterval(progressInterval);
        document.getElementById('progress-fill').style.width = '100%';
        document.getElementById('progress-text').textContent = '查询完成';
        btn.disabled = false;

        setTimeout(() => {
            hideElement('batch-progress');

            if (data.success) {
                showBatchResults(data);
            } else {
                showBatchError(data.error || '批量查询失败');
            }
        }, 500);
    })
    .catch(err => {
        clearInterval(progressInterval);
        hideElement('batch-progress');
        btn.disabled = false;
        showBatchError('网络请求失败，请检查网络连接');
        console.error('批量查询出错:', err);
    });
}

function showBatchResults(data) {
    // 缓存结果用于导出
    batchResults = data.results || [];

    // 统计信息
    const summary = document.getElementById('batch-summary');
    summary.innerHTML = `
        共 <span class="stat">${data.total}</span> 条 &nbsp;|&nbsp;
        成功 <span class="stat stat-success">${data.success_count}</span> 条 &nbsp;|&nbsp;
        失败 <span class="stat stat-fail">${data.fail_count}</span> 条
    `;

    // 构建表格
    const tbody = document.getElementById('result-table-body');
    tbody.innerHTML = '';

    batchResults.forEach((r, idx) => {
        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td>${idx + 1}</td>
            <td>${escapeHtml(r.isbn_input || '')}</td>
            <td>${escapeHtml(r.title || '-')}</td>
            <td class="cell-clc">${escapeHtml(r.clc_code || '-')}</td>
            <td class="cell-path">${escapeHtml(r.clc_path_str || '-')}</td>
            <td class="cell-path">${escapeHtml(r.subject || '-')}</td>
            <td class="${r.success ? 'status-success' : 'status-fail'}">
                ${r.success ? '✓ 成功' : '✗ ' + escapeHtml(r.error || '失败')}
            </td>
        `;
        tbody.appendChild(tr);
    });

    showElement('batch-results');
}

function showBatchError(message) {
    document.getElementById('batch-error-msg').textContent = message;
    showElement('batch-error');
}

// ==================== 导出结果 ====================

function exportResults() {
    if (batchResults.length === 0) {
        showBatchError('无可导出的数据');
        return;
    }

    fetch('/api/export', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ results: batchResults })
    })
    .then(res => {
        if (!res.ok) throw new Error('导出失败');
        return res.blob();
    })
    .then(blob => {
        // 创建下载链接
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = '中图分类号查询结果.xlsx';
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        window.URL.revokeObjectURL(url);
    })
    .catch(err => {
        showBatchError('导出失败，请重试');
        console.error('导出出错:', err);
    });
}

// ==================== 工具函数 ====================

function showElement(id) {
    document.getElementById(id).classList.remove('hidden');
}

function hideElement(id) {
    document.getElementById(id).classList.add('hidden');
}

function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}
