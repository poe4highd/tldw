/* dev.js - 开发页面脚本 */

// 当前处理中的视频ID
let currentVideoId = null;
let lastVideoStatus = {};

// 表单提交处理
document.getElementById('submitForm').addEventListener('submit', async function(e) {
    e.preventDefault();

    const submitBtn = document.getElementById('submitBtn');
    const btnText = document.getElementById('btnText');
    const btnLoading = document.getElementById('btnLoading');
    const message = document.getElementById('message');
    const urlInput = document.getElementById('youtube_url');

    // 显示加载状态
    submitBtn.disabled = true;
    btnText.style.display = 'none';
    btnLoading.style.display = 'inline-block';
    message.style.display = 'none';

    try {
        addLog(`开始提交YouTube链接: ${urlInput.value}`, 'info');

        const formData = new FormData();
        formData.append('youtube_url', urlInput.value);

        const response = await fetch('/submit', {
            method: 'POST',
            body: formData
        });

        const result = await response.json();

        if (response.ok) {
            message.className = 'message success';
            message.textContent = result.message || '视频提交成功，正在处理中...';
            message.style.display = 'block';

            addLog(`视频提交成功，ID: ${result.video_id}`, 'success');
            addLog('开始下载YouTube音频...', 'info');
            currentVideoId = result.video_id;

            // 清空输入框
            urlInput.value = '';

            // 开始监听状态
            setTimeout(() => checkVideoStatus(result.video_id), 2000);
        } else {
            message.className = 'message error';
            message.textContent = result.error || '提交失败';
            message.style.display = 'block';

            addLog(`提交失败: ${result.error}`, 'error');
        }
    } catch (error) {
        message.className = 'message error';
        message.textContent = '网络错误，请重试';
        message.style.display = 'block';

        addLog(`网络错误: ${error.message}`, 'error');
    }

    // 恢复按钮状态
    submitBtn.disabled = false;
    btnText.style.display = 'inline';
    btnLoading.style.display = 'none';
});

// 日志功能
function addLog(message, type = 'info') {
    const logContainer = document.getElementById('logContainer');
    const timestamp = new Date().toLocaleTimeString();
    const logEntry = document.createElement('div');
    logEntry.className = `log-entry log-${type}`;
    logEntry.innerHTML = `<span class="log-timestamp">[${timestamp}]</span> ${message}`;

    logContainer.appendChild(logEntry);
    logContainer.scrollTop = logContainer.scrollHeight;
}

function clearLogs() {
    const logContainer = document.getElementById('logContainer');
    logContainer.innerHTML = '<div class="log-entry log-info"><span class="log-timestamp">[系统]</span> 日志已清除</div>';
}

// 监听处理状态
async function checkVideoStatus(videoId) {
    try {
        const response = await fetch(`/status/${videoId}`);
        const result = await response.json();

        // 只在状态真正发生变化时才更新UI
        if (lastVideoStatus[videoId] !== result.status) {
            lastVideoStatus[videoId] = result.status;

            if (result.status === 'completed') {
                addLog(`视频 ${videoId} 处理完成！`, 'success');
                currentVideoId = null;
                updateFileStatus(videoId, result.file_status);
            } else if (result.status === 'failed') {
                addLog(`视频 ${videoId} 处理失败: ${result.error}`, 'error');
                currentVideoId = null;
            }
        }

        // 更新文件状态
        if (result.file_status && (result.status === 'completed' || result.status === 'failed')) {
            updateFileStatus(videoId, result.file_status);
        }

    } catch (error) {
        addLog(`检查状态时出错: ${error.message}`, 'error');
    }
}

// 获取处理日志的详细信息
async function fetchProcessingLogs(videoId) {
    try {
        const response = await fetch(`/api/logs/${videoId}`);
        const result = await response.json();

        if (result.success && result.logs) {
            const lines = result.logs.split('\n');
            lines.forEach(line => {
                if (line.trim()) {
                    let logType = 'info';
                    if (line.includes('完成') || line.includes('成功')) {
                        logType = 'success';
                    } else if (line.includes('失败') || line.includes('错误')) {
                        logType = 'error';
                    }
                    addLog(line, logType);
                }
            });
        }
    } catch (error) {
        console.warn('获取处理日志失败:', error);
    }
}

// 更新文件状态显示
function updateFileStatus(videoId, fileStatus) {
    const statusElement = document.getElementById(`file-status-${videoId}`);
    if (!statusElement || !fileStatus) return;

    const indicators = statusElement.querySelectorAll('.file-indicator');

    // 更新MP3状态
    if (indicators[0]) {
        if (fileStatus.mp3_exists) {
            indicators[0].className = 'file-indicator exists';
            indicators[0].textContent = `MP3 ${fileStatus.mp3_size}MB`;
            indicators[0].title = `MP3文件已存在 (${fileStatus.mp3_size}MB)`;
        } else {
            indicators[0].className = 'file-indicator missing';
            indicators[0].textContent = 'MP3 -';
            indicators[0].title = 'MP3文件不存在';
        }
    }

    // 更新转录状态
    if (indicators[1]) {
        if (fileStatus.transcript_exists) {
            indicators[1].className = 'file-indicator exists';
            indicators[1].textContent = 'TXT OK';
            indicators[1].title = '转录文件已存在';
        } else {
            indicators[1].className = 'file-indicator missing';
            indicators[1].textContent = 'TXT -';
            indicators[1].title = '转录文件不存在';
        }
    }

    // 更新报告状态
    if (indicators[2]) {
        if (fileStatus.report_exists) {
            indicators[2].className = 'file-indicator exists';
            indicators[2].textContent = 'HTML OK';
            indicators[2].title = '报告文件已存在';
        } else {
            indicators[2].className = 'file-indicator missing';
            indicators[2].textContent = 'HTML -';
            indicators[2].title = '报告文件不存在';
        }
    }
}

// 页面加载完成后初始化文件状态
document.addEventListener('DOMContentLoaded', function() {
    const videoItems = document.querySelectorAll('.video-item');
    videoItems.forEach(item => {
        const statusElement = item.querySelector('[id^="file-status-"]');
        if (statusElement) {
            const videoId = statusElement.id.split('-')[2];
            setTimeout(() => checkVideoStatus(videoId), Math.random() * 2000);
        }
    });
});

// 定时器
let logUpdateInterval;
let statusCheckInterval;

function startLogUpdate() {
    if (logUpdateInterval) clearInterval(logUpdateInterval);
    logUpdateInterval = setInterval(() => {
        if (currentVideoId) {
            fetchProcessingLogs(currentVideoId);
        }
    }, 5000);
}

function startStatusCheck() {
    if (statusCheckInterval) clearInterval(statusCheckInterval);
    statusCheckInterval = setInterval(() => {
        if (currentVideoId) {
            checkVideoStatus(currentVideoId);
        }
    }, 10000);
}

// 启动定时器
startLogUpdate();
startStatusCheck();

// 删除文件功能
async function deleteFile(videoId, deleteType) {
    const confirmMessages = {
        'download': '确定要删除下载的音频文件吗？',
        'transcript': '确定要删除转录文件吗？',
        'report': '确定要删除简报文件吗？',
        'all': '确定要删除所有文件和数据库记录吗？此操作不可恢复！'
    };

    const message = confirmMessages[deleteType];
    if (!confirm(message)) {
        return;
    }

    try {
        addLog(`开始删除视频 ${videoId} 的 ${deleteType} 文件...`, 'info');

        const response = await fetch(`/api/delete/${videoId}/${deleteType}`, {
            method: 'DELETE'
        });

        const result = await response.json();

        if (response.ok) {
            addLog(`删除成功: ${result.message}`, 'success');

            // 如果删除全部，刷新页面
            if (deleteType === 'all') {
                addLog('正在刷新页面...', 'info');
                setTimeout(() => {
                    window.location.reload();
                }, 1000);
            } else {
                // 更新文件状态显示
                setTimeout(() => checkVideoStatus(videoId), 500);
            }
        } else {
            addLog(`删除失败: ${result.error}`, 'error');
        }
    } catch (error) {
        addLog(`删除操作失败: ${error.message}`, 'error');
    }
}
