let username = '';
let ws = null;

async function loadMessages() {
    const response = await fetch(`/api/${API_VERSION}/messages`);
    const data = await response.json();
    const messagesDiv = document.getElementById('messages');
    messagesDiv.innerHTML = '';
    data.messages.forEach(message => {
        appendMessage(message);
    });
}

function setUsername() {
    username = document.getElementById('usernameInput').value.trim();
    if (username) {
        document.getElementById('login').style.display = 'none';
        document.getElementById('chat').style.display = 'block';
        document.getElementById('usernameDisplay').textContent = username;

        loadMessages().then(r => {
            connectWebSocket();
        });

    }
}

function connectWebSocket() {
    ws = new WebSocket(`ws://${window.location.host}/api/${API_VERSION}/ws/${username}`);

    ws.onmessage = function (event) {
        const data = JSON.parse(event.data);

        if (data.type === "connection_info") {
            const instanceInfo = document.getElementById('instance-info') || createInstanceInfoElement();
            instanceInfo.innerText = `Connected to: ${data.instance_info.instance_id} (${data.instance_info.availability_zone})`;
        } else {
            appendMessage(data);
        }
    };

    ws.onclose = function () {
        const instanceInfo = document.getElementById('instance-info');
        if (instanceInfo) {
            instanceInfo.innerText = 'Disconnected - Reconnecting...';
        }
        setTimeout(connectWebSocket, 1000);
    };
}

function createInstanceInfoElement() {
    const instanceInfo = document.createElement('div');
    instanceInfo.id = 'instance-info';
    instanceInfo.style.padding = '10px';
    instanceInfo.style.backgroundColor = '#f0f0f0';
    instanceInfo.style.marginBottom = '10px';
    document.querySelector('#chat-container').prepend(instanceInfo);
    return instanceInfo;
}


function appendMessage(message) {
    const messagesDiv = document.getElementById('messages');
    const messageElement = document.createElement('div');
    messageElement.className = `message ${message.username === username ? 'self' : 'other'}`;
    messageElement.innerHTML = `
        <span class="username">${message.username}</span>
        <span class="timestamp">${message.timestamp}</span>
        <div class="message-content">${message.content}</div>
    `;
    messagesDiv.appendChild(messageElement);
    messagesDiv.scrollTop = messagesDiv.scrollHeight;
}

async function sendMessage() {
    const input = document.getElementById('messageInput');
    const content = input.value.trim();

    if (content && username) {
        try {
            await fetch(`/api/${API_VERSION}/messages`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    username: username,
                    content: content
                })
            });

            input.value = '';
        } catch (error) {
            console.error('Error sending message:', error);
        }
    }
}

document.getElementById('messageInput').addEventListener('keypress', function (e) {
    if (e.key === 'Enter') {
        sendMessage();
    }
});
