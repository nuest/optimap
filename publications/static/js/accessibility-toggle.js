// publications/static/js/accessibility-toggle.js
// High contrast theme toggle with localStorage persistence

(function() {
  'use strict';

  /**
   * Accessibility Toggle Manager
   * Handles high contrast mode toggle and persistence
   */
  class AccessibilityToggle {
    constructor() {
      this.storageKey = 'optimap-high-contrast';
      this.bodyElement = document.body;
      this.toggleButton = null;

      this.init();
    }

    init() {
      // Load saved preference
      this.loadPreference();

      // Create toggle button
      this.createToggleButton();

      // Add event listeners
      this.setupEventListeners();

      // Announce current state to screen readers
      this.announceState();
    }

    /**
     * Load user preference from localStorage
     */
    loadPreference() {
      const saved = localStorage.getItem(this.storageKey);
      if (saved === 'true') {
        this.enable();
      }
    }

    /**
     * Save user preference to localStorage
     */
    savePreference(enabled) {
      localStorage.setItem(this.storageKey, enabled.toString());
    }

    /**
     * Create the floating toggle button
     */
    createToggleButton() {
      this.toggleButton = document.createElement('button');
      this.toggleButton.id = 'accessibility-toggle';
      this.toggleButton.setAttribute('aria-label', 'Toggle high contrast mode');
      this.toggleButton.setAttribute('title', 'Toggle High Contrast Mode');
      this.toggleButton.setAttribute('data-tooltip', 'Toggle High Contrast');
      this.toggleButton.innerHTML = '<i class="fas fa-adjust" aria-hidden="true"></i>';

      document.body.appendChild(this.toggleButton);
    }

    /**
     * Setup event listeners
     */
    setupEventListeners() {
      if (!this.toggleButton) return;

      this.toggleButton.addEventListener('click', () => {
        this.toggle();
      });

      // Keyboard shortcut: Ctrl+Alt+H
      document.addEventListener('keydown', (e) => {
        if (e.ctrlKey && e.altKey && e.key === 'h') {
          e.preventDefault();
          this.toggle();
        }
      });
    }

    /**
     * Toggle high contrast mode
     */
    toggle() {
      if (this.isEnabled()) {
        this.disable();
      } else {
        this.enable();
      }
    }

    /**
     * Enable high contrast mode
     */
    enable() {
      this.bodyElement.classList.add('high-contrast');
      this.savePreference(true);
      this.announceState();
      console.log('High contrast mode enabled');
    }

    /**
     * Disable high contrast mode
     */
    disable() {
      this.bodyElement.classList.remove('high-contrast');
      this.savePreference(false);
      this.announceState();
      console.log('High contrast mode disabled');
    }

    /**
     * Check if high contrast mode is enabled
     */
    isEnabled() {
      return this.bodyElement.classList.contains('high-contrast');
    }

    /**
     * Announce state change to screen readers
     */
    announceState() {
      let announcer = document.getElementById('announcer');
      if (!announcer) {
        announcer = document.createElement('div');
        announcer.id = 'announcer';
        announcer.className = 'sr-only';
        announcer.setAttribute('role', 'status');
        announcer.setAttribute('aria-live', 'polite');
        announcer.setAttribute('aria-atomic', 'true');
        document.body.appendChild(announcer);
      }

      const state = this.isEnabled() ? 'enabled' : 'disabled';
      announcer.textContent = `High contrast mode ${state}`;

      // Update button label
      if (this.toggleButton) {
        this.toggleButton.setAttribute(
          'aria-label',
          `Toggle high contrast mode (currently ${state})`
        );
      }
    }
  }

  // Initialize when DOM is ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
      new AccessibilityToggle();
    });
  } else {
    new AccessibilityToggle();
  }
})();
