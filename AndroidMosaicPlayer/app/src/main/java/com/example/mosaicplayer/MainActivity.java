package com.example.mosaicplayer;

import androidx.appcompat.app.AppCompatActivity;

import android.os.Bundle;
import android.view.View;
import android.widget.Toast;
import android.util.Log;
import android.widget.Button;
import android.widget.EditText;
import com.google.android.exoplayer2.ExoPlayer;
import com.google.android.exoplayer2.MediaItem;
import com.google.android.exoplayer2.source.hls.HlsMediaSource;
import com.google.android.exoplayer2.ui.StyledPlayerView;
import com.google.android.exoplayer2.upstream.DefaultHttpDataSource;

public class MainActivity extends AppCompatActivity {

    private ExoPlayer player;
    private StyledPlayerView playerView;
    private EditText urlInput;
    private Button playButton;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_main);

        playerView = findViewById(R.id.player_view);
        urlInput = findViewById(R.id.url_input);
        playButton = findViewById(R.id.play_button);

        playButton.setOnClickListener(v -> {
            String url = urlInput.getText().toString().trim();
            if (url.isEmpty()) {
                Toast.makeText(this, "Please enter a stream URL", Toast.LENGTH_SHORT).show();
                return;
            }
            
            if (!url.startsWith("http://") && !url.startsWith("https://")) {
                Toast.makeText(this, "URL must start with http:// or https://", Toast.LENGTH_SHORT).show();
                return;
            }
            
            initializePlayer(url);
        });
    }

    private void initializePlayer(String hlsUrl) {
        try {
            if (player != null) {
                player.release();
            }

            player = new ExoPlayer.Builder(this).build();
            playerView.setPlayer(player);

            // Add error listener
            player.addListener(new com.google.android.exoplayer2.Player.Listener() {
                @Override
                public void onPlayerError(com.google.android.exoplayer2.PlaybackException error) {
                    Log.e("MosaicPlayer", "Playback error: " + error.getMessage());
                    Toast.makeText(MainActivity.this, "Playback error: " + error.getMessage(), Toast.LENGTH_LONG).show();
                }
            });

            DefaultHttpDataSource.Factory dataSourceFactory = new DefaultHttpDataSource.Factory();
            HlsMediaSource hlsMediaSource = new HlsMediaSource.Factory(dataSourceFactory)
                    .createMediaSource(MediaItem.fromUri(hlsUrl));

            player.setMediaSource(hlsMediaSource);
            player.setPlayWhenReady(true);
            player.prepare();
            
            Toast.makeText(this, "Loading stream...", Toast.LENGTH_SHORT).show();
        } catch (Exception e) {
            Log.e("MosaicPlayer", "Error initializing player: " + e.getMessage());
            Toast.makeText(this, "Error loading stream: " + e.getMessage(), Toast.LENGTH_LONG).show();
        }
    }

    @Override
    protected void onStart() {
        super.onStart();
        if (player != null) {
            player.setPlayWhenReady(true);
        }
    }

    @Override
    protected void onStop() {
        super.onStop();
        if (player != null) {
            player.setPlayWhenReady(false);
        }
    }

    @Override
    protected void onDestroy() {
        super.onDestroy();
        if (player != null) {
            player.release();
            player = null;
        }
    }
}
