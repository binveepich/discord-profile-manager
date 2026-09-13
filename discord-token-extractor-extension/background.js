chrome.action.onClicked.addListener((tab) => {
  // Kiểm tra xem có phải trang Discord không
  const discordUrls = [
    'discord.com',
    'discordapp.com',
    'ptb.discord.com',
    'canary.discord.com'
  ];
  
  const isDiscord = discordUrls.some(url => tab.url.includes(url));
  
  if (!isDiscord) {
    // Hiển thị thông báo lỗi nếu không phải Discord
    chrome.scripting.executeScript({
      target: { tabId: tab.id },
      func: (currentUrl) => {
        const notification = document.createElement('div');
        notification.style.cssText = `
          position: fixed;
          top: 20px;
          right: 20px;
          background: #f44336;
          color: white;
          padding: 16px 24px;
          border-radius: 8px;
          font-family: Arial, sans-serif;
          z-index: 999999;
          box-shadow: 0 4px 12px rgba(0,0,0,0.3);
          animation: slideIn 0.3s ease;
          border-left: 4px solid #d32f2f;
          max-width: 350px;
        `;
        notification.innerHTML = `
          <div style="display: flex; align-items: center; gap: 12px;">
            <span style="font-size: 24px;">❌</span>
            <div>
              <div style="font-weight: bold; margin-bottom: 4px;">Sai trang web!</div>
              <div style="font-size: 13px; opacity: 0.9;">
                Extension này chỉ hoạt động trên Discord.<br>
                Trang hiện tại: ${new URL(currentUrl).hostname}
              </div>
            </div>
          </div>
        `;
        
        // Thêm animation
        const style = document.createElement('style');
        style.textContent = `
          @keyframes slideIn {
            from { transform: translateX(100%); opacity: 0; }
            to { transform: translateX(0); opacity: 1; }
          }
        `;
        document.head.appendChild(style);
        
        document.body.appendChild(notification);
        
        // Tự động ẩn sau 4 giây
        setTimeout(() => {
          notification.style.transition = 'opacity 0.3s ease';
          notification.style.opacity = '0';
          setTimeout(() => notification.remove(), 300);
        }, 4000);
      },
      args: [tab.url]
    });
    return;
  }
  
  // Nếu là Discord thì chạy bình thường
  chrome.scripting.executeScript({
    target: { tabId: tab.id },
    function: extractDiscordToken
  }).catch(err => {
    console.error('Lỗi:', err);
    chrome.scripting.executeScript({
      target: { tabId: tab.id },
      func: (error) => {
        alert('Không thể lấy token Discord: ' + error.message);
      },
      args: [err]
    });
  });
});

function extractDiscordToken() {
  try {
    // Kiểm tra lại lần nữa bằng URL hiện tại
    if (!window.location.hostname.includes('discord')) {
      throw new Error('Không phải trang Discord');
    }
    
    // Tạo iframe để truy cập localStorage an toàn
    const iframe = document.createElement('iframe');
    document.body.appendChild(iframe);
    
    // Lấy token từ localStorage của iframe
    // Discord thường lưu token ở key "token" hoặc "discord_token"
    let tokenData = iframe.contentWindow.localStorage.getItem('token');
    
    // Thử với các key khác nếu không tìm thấy
    if (!tokenData) {
      tokenData = iframe.contentWindow.localStorage.getItem('discord_token');
    }
    
    if (!tokenData) {
      // Thử tìm bất kỳ key nào có chứa token
      const keys = Object.keys(iframe.contentWindow.localStorage);
      for (const key of keys) {
        if (key.includes('token') && key.includes('discord')) {
          tokenData = iframe.contentWindow.localStorage.getItem(key);
          break;
        }
      }
    }
    
    if (!tokenData) {
      throw new Error('Không tìm thấy token Discord trong localStorage. Hãy đăng nhập Discord trước.');
    }
    
    // Parse JSON nếu cần
    let token = tokenData;
    try {
      // Thử parse JSON (nếu token được lưu dưới dạng JSON)
      const parsed = JSON.parse(tokenData);
      token = parsed.token || parsed;
    } catch (e) {
      // Nếu không parse được, giữ nguyên
    }
    
    // Copy vào clipboard
    navigator.clipboard.writeText(token).then(() => {
      // Thông báo thành công với style Discord
      const notification = document.createElement('div');
      notification.style.cssText = `
        position: fixed;
        top: 20px;
        right: 20px;
        background: #5865F2;
        color: white;
        padding: 16px 24px;
        border-radius: 8px;
        font-family: 'Whitney', 'Helvetica Neue', Arial, sans-serif;
        z-index: 999999;
        box-shadow: 0 4px 12px rgba(0,0,0,0.3);
        animation: slideIn 0.3s ease;
        border-left: 4px solid #4752C4;
        display: flex;
        align-items: center;
        gap: 12px;
      `;
      notification.innerHTML = `
        <span style="font-size: 24px;">✅</span>
        <div>
          <div style="font-weight: bold; margin-bottom: 4px;">Token Discord đã được copy!</div>
          <div style="font-size: 12px; opacity: 0.8;">Token đã được lưu vào clipboard</div>
        </div>
      `;
      
      // Thêm animation
      const style = document.createElement('style');
      style.textContent = `
        @keyframes slideIn {
          from { transform: translateX(100%); opacity: 0; }
          to { transform: translateX(0); opacity: 1; }
        }
      `;
      document.head.appendChild(style);
      
      document.body.appendChild(notification);
      
      // Tự động ẩn sau 3 giây
      setTimeout(() => {
        notification.style.transition = 'opacity 0.3s ease';
        notification.style.opacity = '0';
        setTimeout(() => notification.remove(), 300);
      }, 3000);
    }).catch(clipboardErr => {
      // Fallback cho clipboard cũ
      const textarea = document.createElement('textarea');
      textarea.value = token;
      textarea.style.position = 'fixed';
      textarea.style.opacity = '0';
      document.body.appendChild(textarea);
      textarea.select();
      document.execCommand('copy');
      textarea.remove();
      alert('Token Discord đã được copy vào clipboard!');
    });
    
    // Xóa iframe
    iframe.remove();
    
  } catch (error) {
    console.error('Lỗi:', error);
    
    // Thông báo lỗi với style Discord
    const errorNotification = document.createElement('div');
    errorNotification.style.cssText = `
      position: fixed;
      top: 20px;
      right: 20px;
      background: #ED4245;
      color: white;
      padding: 16px 24px;
      border-radius: 8px;
      font-family: 'Whitney', 'Helvetica Neue', Arial, sans-serif;
      z-index: 999999;
      box-shadow: 0 4px 12px rgba(0,0,0,0.3);
      animation: slideIn 0.3s ease;
      border-left: 4px solid #C0353A;
      display: flex;
      align-items: center;
      gap: 12px;
      max-width: 350px;
    `;
    errorNotification.innerHTML = `
      <span style="font-size: 24px;">⚠️</span>
      <div>
        <div style="font-weight: bold; margin-bottom: 4px;">Lỗi!</div>
        <div style="font-size: 13px; opacity: 0.9;">${error.message}</div>
      </div>
    `;
    
    document.body.appendChild(errorNotification);
    
    setTimeout(() => {
      errorNotification.style.transition = 'opacity 0.3s ease';
      errorNotification.style.opacity = '0';
      setTimeout(() => errorNotification.remove(), 300);
    }, 5000);
    
    // Dọn dẹp nếu có lỗi
    const iframe = document.querySelector('iframe');
    if (iframe) iframe.remove();
  }
}