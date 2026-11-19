(function() {
  'use strict';
  
  function initWatsonCrickHelpModal() {
    // Create modal if it doesn't exist
    if (!document.getElementById('watsoncrickHelpModal')) {
      var modal = document.createElement('div');
      modal.id = 'watsoncrickHelpModal';
      modal.className = 'watsoncrick-modal';
      modal.innerHTML = `
        <div class="watsoncrick-modal-content">
          <span class="watsoncrick-modal-close" id="watsoncrickModalClose">&times;</span>
          <h2>🔬 How to Grant WatsonCrick Lab Access</h2>
          
          <div class="watsoncrick-note">
            <strong>Note:</strong> The <code>WatsonCrick</code> group and <code>watsoncrick.access_watsoncrick</code> permission 
            are automatically created when migrations run. Admins bypass this permission.
          </div>
          
          <h3>Step 1: Add User to WatsonCrick Group</h3>
          <ol>
            <li>Go to <strong>Authentication and Authorization → Groups</strong></li>
            <li>Click on <strong>WatsonCrick</strong></li>
            <li>Under "Available users", select the user you want to grant access to</li>
            <li>Click the right arrow (→) to add them to "Chosen users"</li>
            <li>Click <strong>SAVE</strong> at the bottom</li>
          </ol>
          
          <div class="watsoncrick-warning">
            <strong>Alternative:</strong> You can also edit the user directly under 
            <strong>Authentication and Authorization → Users</strong>, scroll to "Groups" section, 
            and add them to the WatsonCrick group there.
          </div>
          
          <h3>Step 2: Set Blog Role (Optional)</h3>
          <p>If the user needs to create/edit blog posts in addition to accessing WatsonCrick:</p>
          <ol>
            <li>Go to <strong>Auth → User profiles</strong></li>
            <li>Find and edit the user's profile</li>
            <li>Set <strong>Role</strong> to <code>editor</code> (or <code>admin</code>)</li>
            <li>Click <strong>SAVE</strong></li>
          </ol>
          <p><em>Note: A blog editor can also access WatsonCrick if they're in the WatsonCrick group. No special combination role needed.</em></p>
          
          <h3>Step 3: Verify Access</h3>
          <ol>
            <li>Go to <strong>Auth → User profiles</strong></li>
            <li>Look at the <strong>WatsonCrick access</strong> column for that user</li>
            <li>It should show <code>True</code> if they have access (via group or admin bypass)</li>
          </ol>
          
          <div class="watsoncrick-note">
            <strong>Admin Bypass:</strong> Users with <code>is_superuser</code> or profile role <code>admin</code> 
            automatically have access to WatsonCrick without needing to be in the group.
          </div>
        </div>
      `;
      document.body.appendChild(modal);
      
      // Close modal events
      var closeBtn = document.getElementById('watsoncrickModalClose');
      if (closeBtn) {
        closeBtn.onclick = function() {
          modal.classList.remove('active');
        };
      }
      
      modal.onclick = function(e) {
        if (e.target === modal) {
          modal.classList.remove('active');
        }
      };
    }
  }
  
  // Open modal function
  window.showWatsonCrickHelp = function() {
    initWatsonCrickHelpModal();
    var modal = document.getElementById('watsoncrickHelpModal');
    if (modal) {
      modal.classList.add('active');
    }
  };
  
  // Initialize on DOM ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initWatsonCrickHelpModal);
  } else {
    initWatsonCrickHelpModal();
  }
})();
