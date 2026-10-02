import {DirectionProvider} from "../../../../../remotion-composer/src/direction";
import {CapitalFlow} from "./CapitalFlow";

export const Root = (props: {visualTimeline: unknown}) => (
  <DirectionProvider timeline={props.visualTimeline}><CapitalFlow /></DirectionProvider>
);
