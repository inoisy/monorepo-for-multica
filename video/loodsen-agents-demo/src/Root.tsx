import React from 'react';
import {Composition} from 'remotion';
import {Main} from './Main';
import {personas, propsFor} from './data';
import {loadFonts} from './fonts';
import {FPS, H, T, W} from './time';

loadFonts();

export const RemotionRoot: React.FC = () => (
  <>
    <Composition id="Main" component={Main} durationInFrames={T.end} fps={FPS} width={W} height={H} defaultProps={propsFor(personas[0])} />
    {/* Same film, but props are picked by persona id: --props='{"persona":"olga"}' */}
    <Composition
      id="Personal"
      component={Main}
      durationInFrames={T.end}
      fps={FPS}
      width={W}
      height={H}
      defaultProps={propsFor(personas[0])}
      calculateMetadata={({props}) => {
        const id = (props as unknown as {persona?: string}).persona;
        const p = personas.find((x) => x.id === id) ?? personas[0];
        return {props: propsFor(p)};
      }}
    />
  </>
);
