import React from 'react';
import {Composition, registerRoot} from 'remotion';
import {NarratedVideo} from './NarratedVideo';

export const RemotionRoot: React.FC = () => (
  <Composition
    id="NarratedVideo"
    component={NarratedVideo}
    width={1280}
    height={720}
    fps={30}
    durationInFrames={1}
    defaultProps={{width: 1280, height: 720, fps: 30, total_frames: 1, shots: [], motion: {}}}
    calculateMetadata={({props}) => ({
      width: props.width,
      height: props.height,
      fps: props.fps,
      durationInFrames: props.total_frames,
    })}
  />
);

registerRoot(RemotionRoot);
