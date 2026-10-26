(function() {
  'use strict';
  
  function initThalesHelpModal() {
    // Create modal if it doesn't exist
    if (!document.getElementById('thalesHelpModal')) {
      var modal = document.createElement('div');
      modal.id = 'thalesHelpModal';
      modal.className = 'thales-modal';
      modal.innerHTML = `
        <div class="thales-modal-content">
          <span class="thales-modal-close" id="thalesModalClose">&times;</span>
          <h2>🔬 How to Grant Thales Lab Access</h2>
          
          <div class="thales-note">
            <strong>Note:</strong> The <code>Thales</code> group and <code>thales.access_thales</code> permission 
            are automatically created when migrations run. Admins bypass this permission.
          </div>
          
          <h3>Step 1: Add User to Thales Group</h3>
          <ol>
            <li>Go to <strong>Authentication and Authorization → Groups</strong></li>
            <li>Click on <strong>Thales</strong></li>
            <li>Under "Available users", select the user you want to grant access to</li>
            <li>Click the right arrow (→) to add them to "Chosen users"</li>
            <li>Click <strong>SAVE</strong> at the bottom</li>
          </ol>
          
          <div class="thales-warning">
            <strong>Alternative:</strong> You can also edit the user directly under 
            <strong>Authentication and Authorization → Users</strong>, scroll to "Groups" section, 
            and add them to the Thales group there.
          </div>
          
          <h3>Step 2: Set Blog Role (Optional)</h3>
          <p>If the user needs to create/edit blog posts in addition to accessing Thales:</p>
          <ol>
            <li>Go to <strong>Auth → User profiles</strong></li>
            <li>Find and edit the user's profile</li>
            <li>Set <strong>Role</strong> to <code>editor</code> (or <code>admin</code>)</li>
            <li>Click <strong>SAVE</strong></li>
          </ol>
          <p><em>Note: A blog editor can also access Thales if they're in the Thales group. No special combination role needed.</em></p>
          
          <h3>Step 3: Verify Access</h3>
          <ol>
            <li>Go to <strong>Auth → User profiles</strong></li>
            <li>Look at the <strong>Thales access</strong> column for that user</li>
            <li>It should show <code>True</code> if they have access (via group or admin bypass)</li>
          </ol>
          
          <div class="thales-note">
            <strong>Admin Bypass:</strong> Users with <code>is_superuser</code> or profile role <code>admin</code> 
            automatically have access to Thales without needing to be in the group.
          </div>
        </div>
      `;
      document.body.appendChild(modal);
      
      // Close modal events
      var closeBtn = document.getElementById('thalesModalClose');
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
  window.showThalesHelp = function() {
    initThalesHelpModal();
    var modal = document.getElementById('thalesHelpModal');
    if (modal) {
      modal.classList.add('active');
    }
  };
  
  // Initialize on DOM ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initThalesHelpModal);
  } else {
    initThalesHelpModal();
  }
})();
