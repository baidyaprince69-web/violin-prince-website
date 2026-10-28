(function(){
  "use strict";
  var reduced = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var toggle = document.getElementById("site-menu-toggle");
  var menu = document.getElementById("site-navigation");

  function closeMenu(returnFocus){
    if(!toggle || !menu) return;
    menu.classList.remove("is-open");
    toggle.setAttribute("aria-expanded","false");
    toggle.setAttribute("aria-label","Open navigation menu");
    if(returnFocus) toggle.focus();
  }

  if(toggle && menu){
    toggle.addEventListener("click",function(){
      var opening = toggle.getAttribute("aria-expanded") !== "true";
      menu.classList.toggle("is-open",opening);
      toggle.setAttribute("aria-expanded",opening ? "true" : "false");
      toggle.setAttribute("aria-label",opening ? "Close navigation menu" : "Open navigation menu");
    });
    menu.addEventListener("click",function(event){
      if(event.target && event.target.closest && event.target.closest("a")) closeMenu(false);
    });
    document.addEventListener("keydown",function(event){
      if(event.key === "Escape" && toggle.getAttribute("aria-expanded") === "true") closeMenu(true);
    });
    document.addEventListener("click",function(event){
      if(toggle.getAttribute("aria-expanded") === "true" && !menu.contains(event.target) && !toggle.contains(event.target)) closeMenu(false);
    });
    window.addEventListener("resize",function(){ if(window.innerWidth > 780) closeMenu(false); });
  }

  var revealItems = document.querySelectorAll(".reveal");
  if(!reduced && "IntersectionObserver" in window && revealItems.length){
    var observer = new IntersectionObserver(function(entries){
      for(var i=0;i<entries.length;i++){
        if(entries[i].isIntersecting) entries[i].target.classList.add("is-visible");
        else entries[i].target.classList.remove("is-visible");
      }
    },{threshold:0.08,rootMargin:"-8% 0px -8% 0px"});
    for(var r=0;r<revealItems.length;r++) observer.observe(revealItems[r]);
    document.documentElement.classList.add("js-ready");
  } else {
    for(var rr=0;rr<revealItems.length;rr++) revealItems[rr].classList.add("is-visible");
  }

  /* Mood-based song suggestions for the three listening cards. */
  var detailChoices = document.querySelectorAll(".detail-choice[data-song-pick]");
  var songSuggestion = document.getElementById("song-suggestion");
  var suggestionKicker = document.getElementById("suggestion-kicker");
  var suggestionTitle = document.getElementById("suggestion-title");
  var suggestionCopy = document.getElementById("suggestion-copy");
  var suggestionPageLink = document.getElementById("suggestion-page-link");
  var suggestionVideoLink = document.getElementById("suggestion-video-link");
  var songPicks = {
    melody: {
      kicker: "YOUR NEXT LISTEN · EMOTIONAL MELODY",
      title: "Tere Paas Main",
      copy: "For a flowing, emotionally expressive melody, continue with this Violin Prince cover.",
      page: "https://baidyaprince69-web.github.io/violin-prince-website/tere-paas-main/",
      video: "https://www.youtube.com/watch?v=FOV-lwpwcd0",
      pageLabel: "Explore the Tere Paas Main page ↗",
      videoLabel: "Watch Tere Paas Main on YouTube ↗"
    },
    tone: {
      kicker: "YOUR NEXT LISTEN · GENTLE ENGLISH COVER",
      title: "Say You Won't Let Go",
      copy: "For a softer, intimate mood, try this English violin cover next.",
      page: "https://baidyaprince69-web.github.io/violin-prince-website/say-you-wont-let-go/",
      video: "https://www.youtube.com/watch?v=3NHpKon_Uq8",
      pageLabel: "Explore Say You Won't Let Go ↗",
      videoLabel: "Watch Say You Won't Let Go on YouTube ↗"
    },
    space: {
      kicker: "YOUR NEXT LISTEN · NOSTALGIC CLASSIC",
      title: "Hai Apna Dil To Awara",
      copy: "For a breezier, nostalgic tune with room to breathe, explore this classic Hindi song on violin.",
      page: "https://baidyaprince69-web.github.io/violin-prince-website/hai-apna-dil-to-awara/",
      video: "https://www.youtube.com/watch?v=StnvyGduJ0s",
      pageLabel: "Explore Hai Apna Dil To Awara ↗",
      videoLabel: "Watch Hai Apna Dil To Awara on YouTube ↗"
    }
  };
  function revealSongPick(button){
    var pick = songPicks[button.getAttribute("data-song-pick")];
    if(!pick || !songSuggestion) return;
    for(var i=0;i<detailChoices.length;i++){
      detailChoices[i].setAttribute("aria-pressed",detailChoices[i]===button ? "true" : "false");
    }
    if(suggestionKicker) suggestionKicker.textContent = pick.kicker;
    if(suggestionTitle) suggestionTitle.textContent = pick.title;
    if(suggestionCopy) suggestionCopy.textContent = pick.copy;
    if(suggestionPageLink){
      suggestionPageLink.href = pick.page;
      suggestionPageLink.textContent = pick.pageLabel;
      suggestionPageLink.setAttribute("aria-label",pick.pageLabel.replace(" ↗",""));
    }
    if(suggestionVideoLink){
      suggestionVideoLink.href = pick.video;
      suggestionVideoLink.textContent = pick.videoLabel;
      suggestionVideoLink.setAttribute("aria-label",pick.videoLabel.replace(" ↗",""));
    }
    songSuggestion.hidden = false;
    songSuggestion.classList.remove("song-suggestion-active");
    void songSuggestion.offsetWidth;
    songSuggestion.classList.add("song-suggestion-active");
    if(typeof songSuggestion.scrollIntoView === "function"){
      songSuggestion.scrollIntoView({behavior:reduced ? "auto" : "smooth",block:"nearest"});
    }
  }
  for(var choiceIndex=0;choiceIndex<detailChoices.length;choiceIndex++){
    detailChoices[choiceIndex].addEventListener("click",function(){
      revealSongPick(this);
    });
  }

  var bar = document.getElementById("floating-music-bar");
  var frame = document.getElementById("dandelions-video");
  var playButton = document.getElementById("floating-play-button");
  var playIcon = document.getElementById("floating-play-icon");
  var status = document.getElementById("floating-player-status");
  var progress = document.getElementById("floating-progress");
  var currentLabel = document.getElementById("floating-current-time");
  var durationLabel = document.getElementById("floating-duration");
  var jumpButton = document.getElementById("floating-video-jump");
  var directLink = document.getElementById("fallback-youtube-link");
  var poster = document.getElementById("dandelions-poster");
  var pendingPlay = false;
  var player = null;
  var playerReady = false;
  var scrubbing = false;
  var timer = null;
  var duration = 211;

  function formatTime(seconds){
    if(!isFinite(seconds) || seconds < 0) seconds = 0;
    var s = Math.floor(seconds);
    return Math.floor(s/60) + ":" + String(s%60).padStart(2,"0");
  }
  function announce(text){ if(status) status.textContent = text; }
  function hidePoster(moveFocus){
    if(!poster) return;
    poster.classList.add("is-hidden");
    poster.setAttribute("aria-hidden","true");
    poster.disabled = true;
    if(frame){
      frame.setAttribute("tabindex","0");
      if(moveFocus && typeof frame.focus === "function"){
        try{ frame.focus({preventScroll:true}); }catch(e){ frame.focus(); }
      }
    }
  }
  function icon(mode){
    if(!playIcon) return;
    var svgs = {
      play:"<svg viewBox='0 0 20 20' aria-hidden='true' focusable='false'><path d='M6 3.8v12.4c0 .6.7 1 1.2.7l9-6.2a.9.9 0 0 0 0-1.4l-9-6.2c-.5-.3-1.2.1-1.2.7Z' fill='currentColor'></path></svg>",
      pause:"<svg viewBox='0 0 20 20' aria-hidden='true' focusable='false'><rect x='5' y='5' width='3.6' height='10' rx='.8' fill='currentColor'></rect><rect x='11.4' y='5' width='3.6' height='10' rx='.8' fill='currentColor'></rect></svg>",
      replay:"<svg viewBox='0 0 20 20' aria-hidden='true' focusable='false'><path d='M16.3 6.8V2.9L14.8 4.5A7.1 7.1 0 1 0 17 11h-2.3a4.9 4.9 0 1 1-1.5-4.9L11 8.3h5.3V6.8Z' fill='currentColor'></path></svg>"
    };
    playIcon.innerHTML = svgs[mode] || svgs.play;
  }
  function updateProgress(){
    if(!playerReady || !player || scrubbing) return;
    try{
      var d = player.getDuration ? player.getDuration() : duration;
      var now = player.getCurrentTime ? player.getCurrentTime() : 0;
      if(d > 0){
        duration = d;
        progress.value = String(Math.max(0,Math.min(1000,Math.round(now/d*1000))));
        progress.style.setProperty("--bar-progress",(Number(progress.value)/10)+"%");
        currentLabel.textContent = formatTime(now);
        durationLabel.textContent = formatTime(d);
      }
    }catch(e){}
  }
  function onState(event){
    if(!window.YT || !window.YT.PlayerState) return;
    var s = window.YT.PlayerState;
    if(event.data === s.PLAYING){
      hidePoster();
      icon("pause");
      playButton.setAttribute("aria-label","Pause Dandelions violin cover");
      announce("NOW PLAYING · DANDELIONS");
    }else if(event.data === s.PAUSED){
      icon("play");
      playButton.setAttribute("aria-label","Play Dandelions violin cover");
      announce("PAUSED · READY WHEN YOU ARE");
    }else if(event.data === s.ENDED){
      icon("replay");
      playButton.setAttribute("aria-label","Replay Dandelions violin cover");
      announce("PERFORMANCE ENDED · PLAY AGAIN");
      progress.value="0";
      progress.style.setProperty("--bar-progress","0%");
      currentLabel.textContent="0:00";
    }else if(event.data === s.BUFFERING){
      announce("BUFFERING THE PERFORMANCE…");
    }else if(event.data === s.CUED || event.data === s.UNSTARTED){
      icon("play");
      playButton.setAttribute("aria-label","Play Dandelions violin cover");
      announce("READY WHEN YOU ARE");
    }
    updateProgress();
  }
  function playerReadyHandler(event){
    player = event.target;
    playerReady = true;
    playButton.disabled = false;
    progress.disabled = false;
    try{
      duration = player.getDuration() || 211;
      durationLabel.textContent = formatTime(duration);
    }catch(e){ duration = 211; }
    announce("READY WHEN YOU ARE · PRESS PLAY");
    if(timer === null) timer = window.setInterval(updateProgress,500);
    if(pendingPlay){
      pendingPlay = false;
      hidePoster();
      try{ player.playVideo(); announce("STARTING DANDELIONS"); }
      catch(e){ announce("USE THE VIDEO PLAYER ABOVE TO LISTEN"); }
    }
  }

  if(playButton && progress && frame){
    window.onYouTubeIframeAPIReady = function(){
      try{
        player = new YT.Player("dandelions-video",{
          events:{
            onReady:playerReadyHandler,
            onStateChange:onState,
            onError:function(){
              playerReady = false;
              playButton.disabled = true;
              progress.disabled = true;
              hidePoster();
              announce("PLAYER UNAVAILABLE · OPEN THE VIDEO ON YOUTUBE");
            }
          }
        });
      }catch(e){
        announce("USE THE DIRECT YOUTUBE LINK TO LISTEN");
      }
    };
    playButton.addEventListener("click",function(){
      if(!playerReady || !player || !window.YT) return;
      try{
        var state = player.getPlayerState();
        if(state === YT.PlayerState.PLAYING || state === YT.PlayerState.BUFFERING){
          player.pauseVideo();
        }else{
          if(state === YT.PlayerState.ENDED) player.seekTo(0,true);
          hidePoster();
          player.playVideo();
          announce("STARTING DANDELIONS");
        }
      }catch(e){ announce("USE THE VIDEO PLAYER ABOVE TO LISTEN"); }
    });
    progress.addEventListener("input",function(){
      scrubbing = true;
      var d = (playerReady && player && player.getDuration) ? (player.getDuration() || duration) : duration;
      currentLabel.textContent = formatTime(Number(progress.value)/1000*d);
      progress.style.setProperty("--bar-progress",(Number(progress.value)/10)+"%");
    });
    progress.addEventListener("change",function(){
      if(playerReady && player && player.seekTo){
        try{ player.seekTo((Number(progress.value)/1000)*duration,true); }catch(e){}
      }
      scrubbing = false;
      updateProgress();
    });
    if(poster) poster.addEventListener("click",function(){
      if(playerReady && player && typeof player.playVideo === "function"){
        hidePoster(true);
        try{ player.playVideo(); announce("STARTING DANDELIONS"); }
        catch(e){ announce("USE THE DIRECT YOUTUBE LINK TO LISTEN"); }
        return;
      }
      pendingPlay = true;
      announce("CONNECTING TO THE PERFORMANCE…");
      window.setTimeout(function(){
        if(!playerReady){
          hidePoster();
          announce("PLAYER CONTROLS ARE STILL LOADING · USE THE VIDEO OR OPEN YOUTUBE DIRECTLY");
        }
      },5000);
    });
    if(jumpButton) jumpButton.addEventListener("click",function(){
      var target = document.getElementById("cover-player");
      if(target) target.scrollIntoView({behavior:reduced?"auto":"smooth",block:"center"});
    });
    var api = document.createElement("script");
    api.src = "https://www.youtube.com/iframe_api";
    api.async = true;
    api.onerror = function(){ hidePoster(); announce("PLAYER CONTROL UNAVAILABLE · OPEN YOUTUBE DIRECTLY"); };
    document.head.appendChild(api);
  }
  if(directLink){
    directLink.addEventListener("click",function(){ announce("OPENING THE PERFORMANCE ON YOUTUBE"); });
  }
  var year = document.getElementById("current-year");
  if(year) year.textContent = String(new Date().getFullYear());
})();