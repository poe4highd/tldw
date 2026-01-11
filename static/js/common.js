/* common.js - 公共脚本 */

// 格式化日期
function formatDate(dateStr) {
    if (!dateStr || dateStr.length < 8) return dateStr;
    return `${dateStr.slice(0, 4)}-${dateStr.slice(4, 6)}-${dateStr.slice(6, 8)}`;
}

// 格式化时长
function formatDuration(seconds) {
    if (!seconds) return '';
    const minutes = Math.floor(seconds / 60);
    const secs = seconds % 60;
    return `${minutes}:${secs.toString().padStart(2, '0')}`;
}

// 显示消息
function showMessage(element, message, type) {
    if (!element) return;
    element.className = `message ${type}`;
    element.textContent = message;
    element.style.display = 'block';
}

// 隐藏消息
function hideMessage(element) {
    if (!element) return;
    element.style.display = 'none';
}
