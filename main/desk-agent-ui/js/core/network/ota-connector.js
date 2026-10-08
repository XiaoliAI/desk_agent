import { log } from '../../utils/logger.js?v=0207';

export async function webSocketConnect(serverUrl, config) {
    if (!validateConfig(serverUrl, config)) {
        return;
    }

    const connUrl = new URL(serverUrl);
    connUrl.searchParams.set('device-id', config.deviceId);
    connUrl.searchParams.set('client-id', config.clientId || 'desk-agent-ui');

    if (config.token) {
        connUrl.searchParams.set(
            'authorization',
            config.token.startsWith('Bearer ') ? config.token : `Bearer ${config.token}`
        );
    }

    const wsurl = connUrl.toString();
    log(`正在连接: ${wsurl}`, 'info');
    const serverUrlInput = document.getElementById('serverUrl');
    if (serverUrlInput) {
        serverUrlInput.value = wsurl;
    }

    return new WebSocket(wsurl);
}

function validateConfig(serverUrl, config) {
    if (!serverUrl) {
        log('WebSocket服务器地址不能为空', 'error');
        return false;
    }
    if (!config.clientId) {
        log('客户端ID不能为空', 'error');
        return false;
    }
    return true;
}
