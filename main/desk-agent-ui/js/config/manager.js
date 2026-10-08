export const DEFAULT_WAKE_WORDS = '你好小智\n你好小志\n小爱同学\n你好小敏\n你好小新\n小美同学\n小龙小龙\n喵喵同学\n小满小满\n小冰小冰\n嗨你好呀';

function generateRandomMac() {
    const hexDigits = '0123456789ABCDEF';
    let mac = '';
    for (let i = 0; i < 6; i++) {
        if (i > 0) mac += ':';
        for (let j = 0; j < 2; j++) {
            mac += hexDigits.charAt(Math.floor(Math.random() * 16));
        }
    }
    return mac;
}

export function loadConfig() {
    const deviceMacInput = document.getElementById('deviceMac');
    const deviceNameInput = document.getElementById('deviceName');
    const clientIdInput = document.getElementById('clientId');
    const serverUrlInput = document.getElementById('serverUrl');
    const wakewordWsUrlInput = document.getElementById('wakewordWsUrl');
    const wakewordEnabledInput = document.getElementById('wakewordEnabled');
    const wakewordListInput = document.getElementById('wakewordList');

    let savedMac = localStorage.getItem('xz_tester_deviceMac');
    if (!savedMac) {
        savedMac = generateRandomMac();
        localStorage.setItem('xz_tester_deviceMac', savedMac);
    }
    if (deviceMacInput) deviceMacInput.value = savedMac;

    const savedDeviceName = localStorage.getItem('xz_tester_deviceName');
    if (savedDeviceName && deviceNameInput) {
        deviceNameInput.value = savedDeviceName;
    }

    const savedClientId = localStorage.getItem('xz_tester_clientId');
    if (savedClientId && clientIdInput) {
        clientIdInput.value = savedClientId;
    }

    const savedServerUrl = localStorage.getItem('xz_tester_wsUrl');
    if (savedServerUrl && serverUrlInput) {
        serverUrlInput.value = savedServerUrl;
    } else if (serverUrlInput && !serverUrlInput.value) {
        serverUrlInput.value = 'ws://127.0.0.1:8000/xiaozhi/v1/';
    }

    const savedWakewordWsUrl = localStorage.getItem('xz_tester_wakewordWsUrl');
    if (savedWakewordWsUrl !== null && wakewordWsUrlInput) {
        wakewordWsUrlInput.value = savedWakewordWsUrl;
    }

    const savedWakewordEnabled = localStorage.getItem('xz_tester_wakewordEnabled');
    if (savedWakewordEnabled !== null && wakewordEnabledInput) {
        wakewordEnabledInput.value = savedWakewordEnabled;
    }

    const savedWakewordList = localStorage.getItem('xz_tester_wakewordList');
    if (savedWakewordList !== null && wakewordListInput) {
        wakewordListInput.value = savedWakewordList;
    } else if (wakewordListInput) {
        wakewordListInput.value = DEFAULT_WAKE_WORDS;
    }

    const emojiEnabledInput = document.getElementById('emojiEnabled');
    const savedEmojiEnabled = localStorage.getItem('xz_tester_emojiEnabled');
    if (savedEmojiEnabled !== null && emojiEnabledInput) {
        emojiEnabledInput.value = savedEmojiEnabled;
    }
}

export function saveConfig() {
    const deviceMacInput = document.getElementById('deviceMac');
    const deviceNameInput = document.getElementById('deviceName');
    const clientIdInput = document.getElementById('clientId');
    const serverUrlInput = document.getElementById('serverUrl');
    const wakewordWsUrlInput = document.getElementById('wakewordWsUrl');
    const wakewordEnabledInput = document.getElementById('wakewordEnabled');
    const wakewordListInput = document.getElementById('wakewordList');

    if (deviceMacInput) localStorage.setItem('xz_tester_deviceMac', deviceMacInput.value);
    if (deviceNameInput) localStorage.setItem('xz_tester_deviceName', deviceNameInput.value);
    if (clientIdInput) localStorage.setItem('xz_tester_clientId', clientIdInput.value);
    if (serverUrlInput) localStorage.setItem('xz_tester_wsUrl', serverUrlInput.value);

    const emojiEnabledInput = document.getElementById('emojiEnabled');
    if (emojiEnabledInput) {
        localStorage.setItem('xz_tester_emojiEnabled', emojiEnabledInput.value);
    }
    if (wakewordEnabledInput) {
        localStorage.setItem('xz_tester_wakewordEnabled', wakewordEnabledInput.value);
    }
    if (wakewordListInput) {
        localStorage.setItem('xz_tester_wakewordList', wakewordListInput.value);
    }
    if (wakewordWsUrlInput && wakewordWsUrlInput.value.trim()) {
        localStorage.setItem('xz_tester_wakewordWsUrl', wakewordWsUrlInput.value.trim());
    }
}

export function getConfig() {
    const deviceMac = document.getElementById('deviceMac')?.value.trim() || '';
    const deviceName = document.getElementById('deviceName')?.value.trim() || '';
    const clientId = document.getElementById('clientId')?.value.trim() || '';
    const serverUrl = document.getElementById('serverUrl')?.value.trim() || '';
    const emojiEnabled = document.getElementById('emojiEnabled')?.value !== 'false';

    return {
        deviceId: deviceMac,
        deviceName,
        deviceMac,
        clientId,
        serverUrl,
        emojiEnabled
    };
}

export function saveConnectionUrls() {
    const serverUrl = document.getElementById('serverUrl')?.value.trim() || '';
    const wsUrl = document.getElementById('wakewordWsUrl')?.value.trim() || '';
    localStorage.setItem('xz_tester_wsUrl', serverUrl);
    localStorage.setItem('xz_tester_wakewordWsUrl', wsUrl);
}
