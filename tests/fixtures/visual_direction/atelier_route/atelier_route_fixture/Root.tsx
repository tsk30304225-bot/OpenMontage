import { Composition } from "remotion";
import { Scene, calculateMetadata, SceneProps } from "./Composition";

export const Root: React.FC = () => (
  <Composition
    id="AtelierRouteFixture"
    component={Scene}
    durationInFrames={30 * 20}
    fps={30}
    width={1920}
    height={1080}
    defaultProps={{ visualTimeline: { models: [], events: [] }, scenes: [], durationSeconds: 20 } as SceneProps}
    calculateMetadata={calculateMetadata}
  />
);
